use serde::{Deserialize, Serialize};
use serde_json::Value;
use thiserror::Error;

#[derive(Debug, Clone, Copy, Default, PartialEq, Serialize, Deserialize)]
pub struct Vec2 {
    pub x: f32,
    pub y: f32,
}

impl Vec2 {
    pub fn distance(self, other: Self) -> f32 {
        ((self.x - other.x).powi(2) + (self.y - other.y).powi(2)).sqrt()
    }

    pub fn normalized(self) -> Self {
        let length = (self.x * self.x + self.y * self.y).sqrt();
        if length <= f32::EPSILON {
            Self::default()
        } else {
            Self {
                x: self.x / length,
                y: self.y / length,
            }
        }
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord, Hash, Serialize, Deserialize)]
pub struct PlayerKey {
    pub team_id: u8,
    pub player_id: u8,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct Score {
    pub home: u32,
    pub away: u32,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct BallSnapshot {
    pub position: Position3,
    pub velocity: Position3,
    pub is_free: bool,
    pub possession_agent_id: Option<String>,
}

#[derive(Debug, Clone, Copy, Default, Serialize, Deserialize)]
pub struct Position3 {
    pub x: f32,
    pub y: f32,
    pub z: f32,
}

impl From<Vec2> for Position3 {
    fn from(value: Vec2) -> Self {
        Self {
            x: value.x,
            y: value.y,
            z: 0.0,
        }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct PlayerSnapshot {
    pub agent_id: String,
    pub team_code: String,
    pub position: Vec2,
    pub velocity: Vec2,
    pub orientation: f32,
    pub stamina: f32,
    pub current_action: u8,
    pub last_action: String,
    pub speed: f32,
    pub is_sprinting: bool,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct GameState {
    pub tick: u64,
    pub game_time: f32,
    pub play_mode: String,
    pub mode_team_id: Option<u8>,
    pub score: Score,
    pub ball: BallSnapshot,
    pub players: Vec<PlayerSnapshot>,
    pub team_chat: Vec<Value>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct AgentPrompt {
    pub game_state: GameState,
    pub team_id: u8,
    pub my_players: Vec<u8>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct InvokePayload {
    /// AgentCore-compatible envelope. The workshop examples call json.loads on this value.
    pub prompt: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct WireCommand {
    pub command_type: String,
    #[serde(default)]
    pub player_id: Option<u8>,
    #[serde(default)]
    pub team_id: Option<u8>,
    #[serde(default)]
    pub parameters: Value,
    #[serde(default)]
    pub duration: u32,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(tag = "type", rename_all = "SCREAMING_SNAKE_CASE")]
pub enum AgentCommand {
    MoveTo {
        target: Vec2,
        sprint: bool,
    },
    Dribble {
        target: Vec2,
        sprint: bool,
    },
    Pass {
        target_player_id: u8,
        pass_type: String,
    },
    Shoot {
        aim_location: String,
        power: f32,
    },
    Clear,
    GkDistribute {
        target_player_id: u8,
        method: String,
    },
    PressBall {
        intensity: f32,
    },
    Mark {
        target_player_id: u8,
        tightness: String,
    },
    FollowPlayer {
        target_player_id: u8,
        target_team: String,
        distance: f32,
    },
    Intercept {
        aggressive: bool,
    },
    SlideTackle {
        target_player_id: Option<u8>,
        sprint: bool,
        distance: f32,
    },
    SetStance {
        stance: u8,
    },
    ClearOverride,
    Reset,
    Idle,
}

#[derive(Debug, Error)]
pub enum ProtocolError {
    #[error("invalid response JSON: {0}")]
    InvalidJson(#[from] serde_json::Error),
    #[error("agent returned no commands")]
    Empty,
    #[error("agent returned more than one command")]
    Multiple,
    #[error("unknown command {0}")]
    UnknownCommand(String),
    #[error("missing or invalid parameter {0}")]
    InvalidParameter(&'static str),
}

pub fn parse_agent_response(
    body: &str,
    binding: PlayerKey,
) -> Result<(WireCommand, AgentCommand), ProtocolError> {
    let mut value: Value = serde_json::from_str(body)?;
    if let Value::String(inner) = value {
        value = serde_json::from_str(&inner)?;
    }
    let mut commands = match value {
        Value::Array(values) => values,
        Value::Object(_) => vec![value],
        _ => return Err(ProtocolError::Empty),
    };
    if commands.is_empty() {
        return Err(ProtocolError::Empty);
    }
    if commands.len() != 1 {
        return Err(ProtocolError::Multiple);
    }
    let mut wire: WireCommand = serde_json::from_value(commands.remove(0))?;
    wire.team_id = Some(binding.team_id);
    wire.player_id = Some(binding.player_id);
    let p = &wire.parameters;
    let number = |name: &'static str| -> Result<f32, ProtocolError> {
        p.get(name)
            .and_then(Value::as_f64)
            .map(|v| v as f32)
            .ok_or(ProtocolError::InvalidParameter(name))
    };
    let integer = |name: &'static str| -> Result<u8, ProtocolError> {
        p.get(name)
            .and_then(Value::as_u64)
            .and_then(|v| u8::try_from(v).ok())
            .ok_or(ProtocolError::InvalidParameter(name))
    };
    let boolean =
        |name: &'static str, default: bool| p.get(name).and_then(Value::as_bool).unwrap_or(default);
    let target = || -> Result<Vec2, ProtocolError> {
        Ok(Vec2 {
            x: number("target_x")?.clamp(-55.0, 55.0),
            y: number("target_y")?.clamp(-35.0, 35.0),
        })
    };
    let command = match wire.command_type.as_str() {
        "MOVE_TO" => AgentCommand::MoveTo {
            target: target()?,
            sprint: boolean("sprint", false),
        },
        "DRIBBLE" => AgentCommand::Dribble {
            target: target()?,
            sprint: boolean("sprint", false),
        },
        "PASS" => AgentCommand::Pass {
            target_player_id: integer("target_player_id")?,
            pass_type: p
                .get("type")
                .and_then(Value::as_str)
                .unwrap_or("GROUND")
                .to_owned(),
        },
        "SHOOT" => AgentCommand::Shoot {
            aim_location: p
                .get("aim_location")
                .and_then(Value::as_str)
                .unwrap_or("CENTER")
                .to_owned(),
            power: p
                .get("power")
                .and_then(Value::as_f64)
                .unwrap_or(1.0)
                .clamp(0.3, 1.0) as f32,
        },
        "CLEAR" | "CLEAR_BALL" => AgentCommand::Clear,
        "GK_DISTRIBUTE" => AgentCommand::GkDistribute {
            target_player_id: integer("target_player_id")?,
            method: p
                .get("method")
                .and_then(Value::as_str)
                .unwrap_or("KICK")
                .to_owned(),
        },
        "PRESS_BALL" => AgentCommand::PressBall {
            intensity: p
                .get("intensity")
                .and_then(Value::as_f64)
                .unwrap_or(1.0)
                .clamp(0.1, 1.0) as f32,
        },
        "MARK" => AgentCommand::Mark {
            target_player_id: integer("target_player_id")?,
            tightness: p
                .get("tightness")
                .and_then(Value::as_str)
                .unwrap_or("LOOSE")
                .to_owned(),
        },
        "FOLLOW_PLAYER" => AgentCommand::FollowPlayer {
            target_player_id: integer("target_player_id")?,
            target_team: p
                .get("target_team")
                .and_then(Value::as_str)
                .unwrap_or("AWAY")
                .to_owned(),
            distance: p.get("distance").and_then(Value::as_f64).unwrap_or(3.0) as f32,
        },
        "INTERCEPT" => AgentCommand::Intercept {
            aggressive: boolean("aggressive", false),
        },
        "SLIDE_TACKLE" | "TACKLE" => AgentCommand::SlideTackle {
            target_player_id: p
                .get("target_player_id")
                .and_then(Value::as_u64)
                .and_then(|v| u8::try_from(v).ok()),
            sprint: boolean("sprint", false),
            distance: p.get("distance").and_then(Value::as_f64).unwrap_or(3.5) as f32,
        },
        "SET_STANCE" => AgentCommand::SetStance {
            stance: integer("stance")?.min(2),
        },
        "CLEAR_OVERRIDE" => AgentCommand::ClearOverride,
        "RESET" => AgentCommand::Reset,
        "IDLE" => AgentCommand::Idle,
        other => return Err(ProtocolError::UnknownCommand(other.to_owned())),
    };
    Ok((wire, command))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn parses_workshop_command_shape_and_rebinds_identity() {
        let body = r#"[{"commandType":"SHOOT","playerId":99,"parameters":{"aim_location":"TR","power":0.9},"duration":0}]"#;
        let (wire, command) = parse_agent_response(
            body,
            PlayerKey {
                team_id: 0,
                player_id: 3,
            },
        )
        .unwrap();
        assert_eq!(wire.player_id, Some(3));
        assert!(
            matches!(command, AgentCommand::Shoot { aim_location, power } if aim_location == "TR" && power == 0.9)
        );
    }

    #[test]
    fn accepts_agentcore_string_envelope() {
        let inner = r#"[{"commandType":"PRESS_BALL","parameters":{"intensity":2}}]"#;
        let body = serde_json::to_string(inner).unwrap();
        let (_, command) = parse_agent_response(
            &body,
            PlayerKey {
                team_id: 1,
                player_id: 2,
            },
        )
        .unwrap();
        assert!(matches!(command, AgentCommand::PressBall { intensity } if intensity == 1.0));
    }
}
