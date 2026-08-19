use std::{
    collections::BTreeMap,
    fs::File,
    io::{BufWriter, Write},
    path::PathBuf,
    time::{Duration, Instant},
};

use anyhow::{bail, Context, Result};
use clap::{Parser, Subcommand};
use football_core::{MatchConfig, World, PHYSICS_HZ};
use football_protocol::{
    parse_agent_response, AgentCommand, AgentPrompt, InvokePayload, PlayerKey,
};
use futures::future::join_all;
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use sha2::{Digest, Sha256};

#[derive(Parser)]
#[command(
    name = "football-match",
    about = "Local AFC-compatible 5v5 football runner"
)]
struct Cli {
    #[command(subcommand)]
    command: Command,
}

#[derive(Subcommand)]
enum Command {
    Run {
        #[arg(long)]
        agents: PathBuf,
        #[arg(long, default_value = "logs/match.ndjson")]
        log: PathBuf,
        #[arg(long, default_value_t = 42)]
        seed: u64,
        #[arg(long)]
        decisions: Option<u32>,
        #[arg(long, default_value_t = 1000)]
        deadline_ms: u64,
    },
    ValidateAgents {
        #[arg(long)]
        agents: PathBuf,
    },
}

#[derive(Debug, Clone, Deserialize)]
#[serde(rename_all = "camelCase")]
struct AgentsFile {
    agents: Vec<AgentBinding>,
}

#[derive(Debug, Clone, Deserialize, Serialize)]
#[serde(rename_all = "camelCase")]
struct AgentBinding {
    team_id: u8,
    player_id: u8,
    url: String,
    #[serde(default)]
    name: Option<String>,
}

impl AgentBinding {
    fn key(&self) -> PlayerKey {
        PlayerKey {
            team_id: self.team_id,
            player_id: self.player_id,
        }
    }
}

#[derive(Debug, Serialize)]
#[serde(rename_all = "camelCase")]
struct AgentResult {
    team_id: u8,
    player_id: u8,
    url: String,
    status: String,
    latency_ms: u128,
    raw_response: Option<String>,
    wire_command: Option<Value>,
    normalized_command: AgentCommand,
    error: Option<String>,
}

#[tokio::main]
async fn main() -> Result<()> {
    let cli = Cli::parse();
    match cli.command {
        Command::Run {
            agents,
            log,
            seed,
            decisions,
            deadline_ms,
        } => run(agents, log, seed, decisions, deadline_ms).await,
        Command::ValidateAgents { agents } => {
            let config = read_agents(&agents)?;
            validate_bindings(&config.agents)?;
            println!("valid: 10 unique AFC player bindings");
            Ok(())
        }
    }
}

async fn run(
    agents_path: PathBuf,
    log_path: PathBuf,
    seed: u64,
    decisions: Option<u32>,
    deadline_ms: u64,
) -> Result<()> {
    let agents = read_agents(&agents_path)?.agents;
    validate_bindings(&agents)?;
    if let Some(parent) = log_path.parent() {
        std::fs::create_dir_all(parent)?;
    }
    let mut log = BufWriter::new(
        File::create(&log_path).with_context(|| format!("creating {}", log_path.display()))?,
    );
    let config = MatchConfig::default();
    let max_decisions = decisions
        .unwrap_or((config.duration_seconds / config.decision_interval_seconds).ceil() as u32);
    let mut world = World::new(config.clone(), seed);
    let client = reqwest::Client::builder().build()?;

    write_line(
        &mut log,
        &json!({
            "type": "match_started", "schemaVersion": "afc-local/v1", "seed": seed,
            "matchConfig": config, "agents": agents, "world": world.snapshot(),
            "stateHash": state_hash(&world.snapshot())
        }),
    )?;

    for decision_tick in 0..max_decisions {
        if world.ended {
            break;
        }
        let before = world.snapshot();
        let before_hash = state_hash(&before);
        let calls = agents.iter().cloned().map(|binding| {
            let client = client.clone();
            let state = before.clone();
            async move { call_agent(client, binding, state, deadline_ms).await }
        });
        let results = join_all(calls).await;
        let mut batch = BTreeMap::new();
        for result in &results {
            batch.insert(
                PlayerKey {
                    team_id: result.team_id,
                    player_id: result.player_id,
                },
                result.normalized_command.clone(),
            );
        }
        let mut events = world.apply_commands(&batch);
        let steps = (config.decision_interval_seconds * PHYSICS_HZ as f32).round() as u32;
        events.extend(world.advance_steps(steps));
        let after = world.snapshot();
        write_line(
            &mut log,
            &json!({
                "type": "decision", "decisionTick": decision_tick, "worldBefore": before,
                "worldBeforeHash": before_hash, "agentResults": results, "events": events,
                "worldAfter": after, "worldAfterHash": state_hash(&world.snapshot())
            }),
        )?;
    }
    write_line(
        &mut log,
        &json!({
            "type": "match_ended", "score": world.score, "gameTime": world.game_time(),
            "world": world.snapshot(), "stateHash": state_hash(&world.snapshot())
        }),
    )?;
    log.flush()?;
    println!(
        "match complete: {}-{} at {:.1}s -> {}",
        world.score.home,
        world.score.away,
        world.game_time(),
        log_path.display()
    );
    Ok(())
}

async fn call_agent(
    client: reqwest::Client,
    binding: AgentBinding,
    game_state: football_protocol::GameState,
    deadline_ms: u64,
) -> AgentResult {
    let prompt = AgentPrompt {
        game_state,
        team_id: binding.team_id,
        my_players: vec![binding.player_id],
    };
    let payload = InvokePayload {
        prompt: serde_json::to_string(&prompt).expect("serializable prompt"),
    };
    let started = Instant::now();
    let request = client.post(&binding.url).json(&payload).send();
    let response = tokio::time::timeout(Duration::from_millis(deadline_ms), request).await;
    let elapsed = started.elapsed().as_millis();
    let idle = |status: &str, error: String, raw_response: Option<String>| AgentResult {
        team_id: binding.team_id,
        player_id: binding.player_id,
        url: binding.url.clone(),
        status: status.into(),
        latency_ms: elapsed,
        raw_response,
        wire_command: None,
        normalized_command: AgentCommand::Idle,
        error: Some(error),
    };
    let response = match response {
        Err(_) => {
            return idle(
                "timeout",
                format!("deadline exceeded ({deadline_ms}ms)"),
                None,
            )
        }
        Ok(Err(error)) => return idle("http_error", error.to_string(), None),
        Ok(Ok(response)) => response,
    };
    if !response.status().is_success() {
        return idle("http_error", format!("HTTP {}", response.status()), None);
    }
    let body = match response.text().await {
        Ok(body) => body,
        Err(error) => return idle("http_error", error.to_string(), None),
    };
    match parse_agent_response(&body, binding.key()) {
        Ok((wire, command)) => AgentResult {
            team_id: binding.team_id,
            player_id: binding.player_id,
            url: binding.url,
            status: "valid".into(),
            latency_ms: elapsed,
            raw_response: Some(body),
            wire_command: serde_json::to_value(wire).ok(),
            normalized_command: command,
            error: None,
        },
        Err(error) => idle("schema_error", error.to_string(), Some(body)),
    }
}

fn read_agents(path: &PathBuf) -> Result<AgentsFile> {
    let input =
        std::fs::read_to_string(path).with_context(|| format!("reading {}", path.display()))?;
    serde_yaml::from_str(&input).with_context(|| format!("parsing {}", path.display()))
}

fn validate_bindings(agents: &[AgentBinding]) -> Result<()> {
    if agents.len() != 10 {
        bail!("expected exactly 10 agents, got {}", agents.len());
    }
    let keys: std::collections::BTreeSet<_> = agents.iter().map(AgentBinding::key).collect();
    let expected: std::collections::BTreeSet<_> = (0..=1)
        .flat_map(|team_id| (0..5).map(move |player_id| PlayerKey { team_id, player_id }))
        .collect();
    if keys != expected {
        bail!("bindings must contain every (teamId 0..1, playerId 0..4) exactly once");
    }
    Ok(())
}

fn state_hash<T: Serialize>(value: &T) -> String {
    let bytes = serde_json::to_vec(value).expect("serializable state");
    format!("{:x}", Sha256::digest(bytes))
}

fn write_line<W: Write>(writer: &mut W, value: &Value) -> Result<()> {
    serde_json::to_writer(&mut *writer, value)?;
    writer.write_all(b"\n")?;
    Ok(())
}
