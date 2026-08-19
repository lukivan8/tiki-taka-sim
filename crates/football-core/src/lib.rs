use std::collections::BTreeMap;

use football_protocol::{
    AgentCommand, BallSnapshot, GameState, PlayerKey, PlayerSnapshot, Position3, Score, Vec2,
};
use serde::{Deserialize, Serialize};

pub const PHYSICS_HZ: u32 = 60;
pub const FIELD_X: f32 = 55.0;
pub const FIELD_Y: f32 = 35.0;
const GOAL_HALF_WIDTH: f32 = 10.0;
const PLAYER_SPEED: f32 = 8.0;
const SPRINT_SPEED: f32 = 11.0;
const CONTROL_DISTANCE: f32 = 2.35;

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct MatchConfig {
    pub duration_seconds: f32,
    pub decision_interval_seconds: f32,
}

impl Default for MatchConfig {
    fn default() -> Self {
        Self {
            duration_seconds: 120.0,
            decision_interval_seconds: 2.0,
        }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct PlayerState {
    pub key: PlayerKey,
    pub position: Vec2,
    pub velocity: Vec2,
    pub orientation: f32,
    pub stamina: f32,
    pub stance: u8,
    pub last_action: String,
    pub is_sprinting: bool,
    #[serde(skip)]
    intent: Option<Intent>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct BallState {
    pub position: Vec2,
    pub velocity: Vec2,
    pub owner: Option<PlayerKey>,
}

#[derive(Debug, Clone)]
enum Intent {
    Move { target: Vec2, sprint: bool },
    Press { intensity: f32 },
    Mark { target: PlayerKey, distance: f32 },
    Intercept { aggressive: bool },
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(tag = "type", rename_all = "SCREAMING_SNAKE_CASE")]
pub enum GameEvent {
    CommandApplied {
        player: PlayerKey,
        command: String,
    },
    CommandRejected {
        player: PlayerKey,
        reason: String,
    },
    BallKicked {
        player: PlayerKey,
        kind: String,
    },
    PossessionChanged {
        from: Option<PlayerKey>,
        to: Option<PlayerKey>,
    },
    Tackle {
        player: PlayerKey,
        success: bool,
    },
    Goal {
        team_id: u8,
        home: u32,
        away: u32,
    },
    MatchEnded {
        home: u32,
        away: u32,
    },
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct World {
    pub config: MatchConfig,
    pub seed: u64,
    pub tick: u64,
    pub score: Score,
    pub ball: BallState,
    pub players: BTreeMap<PlayerKey, PlayerState>,
    pub ended: bool,
}

impl World {
    pub fn new(config: MatchConfig, seed: u64) -> Self {
        let mut players = BTreeMap::new();
        let formation = [
            (-50.0, 0.0),
            (-27.0, 4.0),
            (-5.0, -4.0),
            (20.0, -10.0),
            (20.0, 10.0),
        ];
        for team_id in 0..=1 {
            for (player_id, &(x, y)) in formation.iter().enumerate() {
                let position = if team_id == 0 {
                    Vec2 { x, y }
                } else {
                    Vec2 { x: -x, y: -y }
                };
                let key = PlayerKey {
                    team_id,
                    player_id: player_id as u8,
                };
                players.insert(
                    key,
                    PlayerState {
                        key,
                        position,
                        velocity: Vec2::default(),
                        orientation: if team_id == 0 {
                            0.0
                        } else {
                            std::f32::consts::PI
                        },
                        stamina: 1.0,
                        stance: 0,
                        last_action: "IDLE".into(),
                        is_sprinting: false,
                        intent: None,
                    },
                );
            }
        }
        Self {
            config,
            seed,
            tick: 0,
            score: Score { home: 0, away: 0 },
            ball: BallState {
                position: Vec2::default(),
                velocity: Vec2::default(),
                owner: None,
            },
            players,
            ended: false,
        }
    }

    pub fn game_time(&self) -> f32 {
        self.tick as f32 / PHYSICS_HZ as f32
    }

    pub fn snapshot(&self) -> GameState {
        let players = self
            .players
            .values()
            .map(|p| PlayerSnapshot {
                agent_id: format!("agentId_{}", p.key.player_id),
                team_code: if p.key.team_id == 0 { "home" } else { "away" }.to_owned(),
                position: p.position,
                velocity: p.velocity,
                orientation: p.orientation,
                stamina: p.stamina,
                current_action: if p.intent.is_some() { 1 } else { 0 },
                last_action: p.last_action.clone(),
                speed: (p.velocity.x.powi(2) + p.velocity.y.powi(2)).sqrt(),
                is_sprinting: p.is_sprinting,
            })
            .collect();
        GameState {
            tick: self.tick,
            game_time: self.game_time(),
            play_mode: if self.ended { "FULL_TIME" } else { "OPEN_PLAY" }.into(),
            mode_team_id: None,
            score: self.score.clone(),
            ball: BallSnapshot {
                position: Position3::from(self.ball.position),
                velocity: Position3::from(self.ball.velocity),
                is_free: self.ball.owner.is_none(),
                possession_agent_id: self.ball.owner.map(|k| format!("agentId_{}", k.player_id)),
            },
            players,
            team_chat: vec![],
        }
    }

    pub fn apply_commands(
        &mut self,
        commands: &BTreeMap<PlayerKey, AgentCommand>,
    ) -> Vec<GameEvent> {
        let before = self.ball.owner;
        let mut events = Vec::new();
        for (&key, command) in commands {
            if !self.players.contains_key(&key) {
                continue;
            }
            let name = command_name(command).to_owned();
            let result = self.apply_command(key, command.clone(), &mut events);
            match result {
                Ok(()) => events.push(GameEvent::CommandApplied {
                    player: key,
                    command: name,
                }),
                Err(reason) => events.push(GameEvent::CommandRejected {
                    player: key,
                    reason,
                }),
            }
        }
        if before != self.ball.owner {
            events.push(GameEvent::PossessionChanged {
                from: before,
                to: self.ball.owner,
            });
        }
        events
    }

    fn apply_command(
        &mut self,
        key: PlayerKey,
        command: AgentCommand,
        events: &mut Vec<GameEvent>,
    ) -> Result<(), String> {
        let player = self.players.get_mut(&key).expect("checked above");
        player.last_action = command_name(&command).to_owned();
        match command {
            AgentCommand::MoveTo { target, sprint } | AgentCommand::Dribble { target, sprint } => {
                player.intent = Some(Intent::Move { target, sprint });
            }
            AgentCommand::PressBall { intensity } => {
                player.intent = Some(Intent::Press { intensity })
            }
            AgentCommand::Mark {
                target_player_id,
                tightness,
            } => {
                player.intent = Some(Intent::Mark {
                    target: PlayerKey {
                        team_id: 1 - key.team_id,
                        player_id: target_player_id.min(4),
                    },
                    distance: if tightness == "TIGHT" { 2.5 } else { 5.0 },
                });
            }
            AgentCommand::FollowPlayer {
                target_player_id,
                target_team,
                distance,
            } => {
                let target_team = if target_team.eq_ignore_ascii_case("HOME") {
                    0
                } else {
                    1
                };
                player.intent = Some(Intent::Mark {
                    target: PlayerKey {
                        team_id: target_team,
                        player_id: target_player_id.min(4),
                    },
                    distance,
                });
            }
            AgentCommand::Intercept { aggressive } => {
                player.intent = Some(Intent::Intercept { aggressive })
            }
            AgentCommand::SetStance { stance } => player.stance = stance.min(2),
            AgentCommand::ClearOverride | AgentCommand::Reset | AgentCommand::Idle => {
                player.intent = None;
                player.is_sprinting = false;
                if matches!(command, AgentCommand::Reset) {
                    player.stance = 0;
                }
            }
            AgentCommand::Pass {
                target_player_id,
                pass_type,
            } => {
                if self.ball.owner != Some(key) {
                    return Err("PASS requires possession".into());
                }
                let target_key = PlayerKey {
                    team_id: key.team_id,
                    player_id: target_player_id.min(4),
                };
                if target_key == key {
                    return Err("cannot pass to self".into());
                }
                let target = self
                    .players
                    .get(&target_key)
                    .ok_or("target player not found")?
                    .position;
                let lead = self.players[&target_key].velocity;
                let direction = Vec2 {
                    x: target.x + lead.x * 0.7 - self.ball.position.x,
                    y: target.y + lead.y * 0.7 - self.ball.position.y,
                }
                .normalized();
                let speed = if pass_type == "THROUGH" {
                    24.0
                } else if pass_type == "AERIAL" {
                    21.0
                } else {
                    18.0
                };
                self.kick(key, direction, speed, "PASS", events);
            }
            AgentCommand::Shoot {
                aim_location,
                power,
            } => {
                if self.ball.owner != Some(key) {
                    return Err("SHOOT requires possession".into());
                }
                let goal_x = if key.team_id == 0 {
                    FIELD_X + 1.0
                } else {
                    -FIELD_X - 1.0
                };
                let target_y = match aim_location.as_str() {
                    "TL" | "BL" => -7.0,
                    "TR" | "BR" => 7.0,
                    _ => 0.0,
                };
                let direction = Vec2 {
                    x: goal_x - self.ball.position.x,
                    y: target_y - self.ball.position.y,
                }
                .normalized();
                self.kick(key, direction, 30.0 * power, "SHOOT", events);
            }
            AgentCommand::Clear => {
                if self.ball.owner != Some(key) {
                    return Err("CLEAR requires possession".into());
                }
                let direction = Vec2 {
                    x: if key.team_id == 0 { 1.0 } else { -1.0 },
                    y: if key.player_id % 2 == 0 { 0.3 } else { -0.3 },
                }
                .normalized();
                self.kick(key, direction, 27.0, "CLEAR", events);
            }
            AgentCommand::GkDistribute {
                target_player_id,
                method,
            } => {
                if key.player_id != 0 {
                    return Err("GK_DISTRIBUTE is goalkeeper-only".into());
                }
                if self.ball.owner != Some(key) {
                    return Err("GK_DISTRIBUTE requires possession".into());
                }
                let target = PlayerKey {
                    team_id: key.team_id,
                    player_id: target_player_id.min(4),
                };
                let direction = Vec2 {
                    x: self.players[&target].position.x - self.ball.position.x,
                    y: self.players[&target].position.y - self.ball.position.y,
                }
                .normalized();
                self.kick(
                    key,
                    direction,
                    if method == "THROW" { 15.0 } else { 23.0 },
                    "GK_DISTRIBUTE",
                    events,
                );
            }
            AgentCommand::SlideTackle {
                target_player_id,
                distance,
                ..
            } => {
                let victim = target_player_id
                    .map(|player_id| PlayerKey {
                        team_id: 1 - key.team_id,
                        player_id: player_id.min(4),
                    })
                    .or(self.ball.owner);
                let success = victim
                    .filter(|v| self.players.contains_key(v))
                    .map(|v| {
                        self.players[&key]
                            .position
                            .distance(self.players[&v].position)
                            <= distance.clamp(2.0, 5.0)
                    })
                    .unwrap_or(false);
                if success {
                    self.ball.owner = Some(key);
                    self.ball.position = self.players[&key].position;
                    self.ball.velocity = Vec2::default();
                }
                events.push(GameEvent::Tackle {
                    player: key,
                    success,
                });
            }
        }
        Ok(())
    }

    fn kick(
        &mut self,
        key: PlayerKey,
        direction: Vec2,
        speed: f32,
        kind: &str,
        events: &mut Vec<GameEvent>,
    ) {
        self.ball.owner = None;
        self.ball.velocity = Vec2 {
            x: direction.x * speed,
            y: direction.y * speed,
        };
        self.ball.position.x += direction.x * 0.8;
        self.ball.position.y += direction.y * 0.8;
        events.push(GameEvent::BallKicked {
            player: key,
            kind: kind.to_owned(),
        });
    }

    pub fn advance_steps(&mut self, steps: u32) -> Vec<GameEvent> {
        let mut events = Vec::new();
        for _ in 0..steps {
            if self.ended {
                break;
            }
            self.step();
            self.tick += 1;
            if let Some(team_id) = self.detect_goal() {
                if team_id == 0 {
                    self.score.home += 1
                } else {
                    self.score.away += 1
                }
                events.push(GameEvent::Goal {
                    team_id,
                    home: self.score.home,
                    away: self.score.away,
                });
                self.reset_positions();
            }
            if self.game_time() >= self.config.duration_seconds {
                self.ended = true;
                events.push(GameEvent::MatchEnded {
                    home: self.score.home,
                    away: self.score.away,
                });
            }
        }
        events
    }

    fn step(&mut self) {
        let dt = 1.0 / PHYSICS_HZ as f32;
        let ball_position = self.ball.position;
        let ball_owner = self.ball.owner;
        let positions: BTreeMap<_, _> =
            self.players.iter().map(|(k, p)| (*k, p.position)).collect();
        for player in self.players.values_mut() {
            let target_and_sprint = match &player.intent {
                Some(Intent::Move { target, sprint }) => Some((*target, *sprint)),
                Some(Intent::Press { intensity }) => Some((
                    ball_owner
                        .and_then(|k| positions.get(&k).copied())
                        .unwrap_or(ball_position),
                    *intensity > 0.65,
                )),
                Some(Intent::Mark { target, distance }) => positions.get(target).map(|pos| {
                    let own_goal = Vec2 {
                        x: if player.key.team_id == 0 {
                            -FIELD_X
                        } else {
                            FIELD_X
                        },
                        y: 0.0,
                    };
                    let away = Vec2 {
                        x: own_goal.x - pos.x,
                        y: own_goal.y - pos.y,
                    }
                    .normalized();
                    (
                        Vec2 {
                            x: pos.x + away.x * *distance,
                            y: pos.y + away.y * *distance,
                        },
                        false,
                    )
                }),
                Some(Intent::Intercept { aggressive }) => Some((
                    Vec2 {
                        x: ball_position.x + self.ball.velocity.x * 0.4,
                        y: ball_position.y + self.ball.velocity.y * 0.4,
                    },
                    *aggressive,
                )),
                None => None,
            };
            if let Some((target, sprint)) = target_and_sprint {
                let delta = Vec2 {
                    x: target.x - player.position.x,
                    y: target.y - player.position.y,
                };
                let direction = delta.normalized();
                let stance_factor = match player.stance {
                    1 => 1.05,
                    2 => 0.92,
                    _ => 1.0,
                };
                let wants_sprint = sprint && player.stamina > 0.05;
                let speed = if wants_sprint {
                    SPRINT_SPEED
                } else {
                    PLAYER_SPEED
                } * stance_factor;
                if delta.distance(Vec2::default()) < 0.15 {
                    player.velocity = Vec2::default();
                } else {
                    player.velocity = Vec2 {
                        x: direction.x * speed,
                        y: direction.y * speed,
                    };
                    player.orientation = direction.y.atan2(direction.x);
                }
                player.is_sprinting = wants_sprint;
                player.stamina =
                    (player.stamina + if wants_sprint { -0.0018 } else { 0.0006 }).clamp(0.0, 1.0);
            } else {
                player.velocity.x *= 0.82;
                player.velocity.y *= 0.82;
                player.stamina = (player.stamina + 0.0008).min(1.0);
            }
            player.position.x =
                (player.position.x + player.velocity.x * dt).clamp(-FIELD_X + 0.8, FIELD_X - 0.8);
            player.position.y =
                (player.position.y + player.velocity.y * dt).clamp(-FIELD_Y + 0.8, FIELD_Y - 0.8);
        }

        if let Some(owner) = self.ball.owner {
            let p = &self.players[&owner];
            let direction = Vec2 {
                x: p.orientation.cos(),
                y: p.orientation.sin(),
            };
            self.ball.position = Vec2 {
                x: p.position.x + direction.x * 1.55,
                y: p.position.y + direction.y * 1.55,
            };
            self.ball.velocity = p.velocity;
        } else {
            self.ball.position.x += self.ball.velocity.x * dt;
            self.ball.position.y += self.ball.velocity.y * dt;
            self.ball.velocity.x *= 0.992;
            self.ball.velocity.y *= 0.992;
            if self.ball.position.y.abs() > FIELD_Y {
                self.ball.position.y = self.ball.position.y.clamp(-FIELD_Y, FIELD_Y);
                self.ball.velocity.y = -self.ball.velocity.y * 0.65;
            }
            if self.ball.position.x.abs() > FIELD_X && self.ball.position.y.abs() >= GOAL_HALF_WIDTH
            {
                self.ball.position.x = self.ball.position.x.clamp(-FIELD_X, FIELD_X);
                self.ball.velocity.x = -self.ball.velocity.x * 0.65;
            }
            let winner = self
                .players
                .iter()
                .filter(|(_, p)| p.position.distance(self.ball.position) <= CONTROL_DISTANCE)
                .min_by(|(ka, pa), (kb, pb)| {
                    pa.position
                        .distance(self.ball.position)
                        .total_cmp(&pb.position.distance(self.ball.position))
                        .then_with(|| ka.cmp(kb))
                })
                .map(|(key, _)| *key);
            if let Some(owner) = winner {
                self.ball.owner = Some(owner);
                self.ball.velocity = Vec2::default();
            }
        }
    }

    fn detect_goal(&self) -> Option<u8> {
        if self.ball.position.y.abs() >= GOAL_HALF_WIDTH {
            return None;
        }
        if self.ball.position.x > FIELD_X {
            Some(0)
        } else if self.ball.position.x < -FIELD_X {
            Some(1)
        } else {
            None
        }
    }

    fn reset_positions(&mut self) {
        let reset = Self::new(self.config.clone(), self.seed);
        for (key, player) in reset.players {
            let current = self.players.get_mut(&key).unwrap();
            current.position = player.position;
            current.velocity = Vec2::default();
            current.intent = None;
        }
        self.ball = BallState {
            position: Vec2::default(),
            velocity: Vec2::default(),
            owner: None,
        };
    }
}

fn command_name(command: &AgentCommand) -> &'static str {
    match command {
        AgentCommand::MoveTo { .. } => "MOVE_TO",
        AgentCommand::Dribble { .. } => "DRIBBLE",
        AgentCommand::Pass { .. } => "PASS",
        AgentCommand::Shoot { .. } => "SHOOT",
        AgentCommand::Clear => "CLEAR",
        AgentCommand::GkDistribute { .. } => "GK_DISTRIBUTE",
        AgentCommand::PressBall { .. } => "PRESS_BALL",
        AgentCommand::Mark { .. } => "MARK",
        AgentCommand::FollowPlayer { .. } => "FOLLOW_PLAYER",
        AgentCommand::Intercept { .. } => "INTERCEPT",
        AgentCommand::SlideTackle { .. } => "SLIDE_TACKLE",
        AgentCommand::SetStance { .. } => "SET_STANCE",
        AgentCommand::ClearOverride => "CLEAR_OVERRIDE",
        AgentCommand::Reset => "RESET",
        AgentCommand::Idle => "IDLE",
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn workshop_snapshot_has_ten_players_and_duplicate_agent_ids_by_team() {
        let state = World::new(MatchConfig::default(), 42).snapshot();
        assert_eq!(state.players.len(), 10);
        assert_eq!(
            state
                .players
                .iter()
                .filter(|p| p.agent_id == "agentId_3")
                .count(),
            2
        );
    }

    #[test]
    fn pass_changes_world_not_just_log() {
        let mut world = World::new(MatchConfig::default(), 42);
        let owner = PlayerKey {
            team_id: 0,
            player_id: 2,
        };
        world.ball.owner = Some(owner);
        world.ball.position = world.players[&owner].position;
        let mut commands = BTreeMap::new();
        commands.insert(
            owner,
            AgentCommand::Pass {
                target_player_id: 3,
                pass_type: "THROUGH".into(),
            },
        );
        world.apply_commands(&commands);
        assert!(world.ball.owner.is_none());
        assert!(world.ball.velocity.x > 0.0);
    }

    #[test]
    fn same_commands_produce_same_snapshot() {
        let mut a = World::new(MatchConfig::default(), 7);
        let mut b = World::new(MatchConfig::default(), 7);
        let key = PlayerKey {
            team_id: 0,
            player_id: 3,
        };
        let commands = BTreeMap::from([(
            key,
            AgentCommand::MoveTo {
                target: Vec2 { x: 40.0, y: 0.0 },
                sprint: true,
            },
        )]);
        a.apply_commands(&commands);
        b.apply_commands(&commands);
        a.advance_steps(120);
        b.advance_steps(120);
        assert_eq!(
            serde_json::to_value(a.snapshot()).unwrap(),
            serde_json::to_value(b.snapshot()).unwrap()
        );
    }
}
