from dataclasses import dataclass, field


@dataclass
class StateTransition:
    from_state: str
    to_state: str
    allowed_signals: list[str]
    description: str = ""


@dataclass
class PoolStateTemplate:
    pool_id: str
    initial_state: str
    terminal_states: set[str]
    transitions: list[StateTransition] = field(default_factory=list)

    def get_next_state(self, current_state: str, signal: str) -> str | None:
        """根据当前状态和信号查找下一状态，找不到返回 None 表示非法转换"""
        for transition in self.transitions:
            if transition.from_state == current_state and signal in transition.allowed_signals:
                return transition.to_state
        return None

    def is_terminal(self, state: str) -> bool:
        return state in self.terminal_states


class PoolStateTemplateRegistry:
    """全局池模板注册表"""

    def __init__(self):
        self._templates: dict[str, PoolStateTemplate] = {}
        self._register_defaults()

    def _register_defaults(self):
        work_template = PoolStateTemplate(
            pool_id="work",
            initial_state="state_0",
            terminal_states={"state_3", "state_timeout"},
            transitions=[
                StateTransition("state_0", "state_1", ["online"], "idle -> online"),
                StateTransition("state_1", "state_2", ["start_writing"], "online -> writing"),
                StateTransition("state_2", "state_3", ["done"], "writing -> done"),
                StateTransition("state_1", "state_0", ["blocked"], "online -> blocked, reset"),
                StateTransition("state_2", "state_0", ["blocked"], "writing -> blocked, reset"),
                StateTransition("state_0", "state_0", ["failed"], "any -> failed"),
                StateTransition("state_1", "state_0", ["failed"], "any -> failed"),
                StateTransition("state_2", "state_0", ["failed"], "any -> failed"),
                StateTransition("state_1", "state_timeout", ["timeout"], "online -> timeout"),
                StateTransition("state_2", "state_timeout", ["timeout"], "writing -> timeout"),
            ],
        )
        self._templates["work"] = work_template

        thinking_template = PoolStateTemplate(
            pool_id="thinking",
            initial_state="state_0",
            terminal_states={"state_4", "state_timeout"},
            transitions=[
                StateTransition("state_0", "state_1", ["online"], "idle -> online"),
                StateTransition("state_1", "state_2", ["start_thinking"], "online -> thinking"),
                StateTransition("state_2", "state_3", ["start_summarizing"], "thinking -> summarizing"),
                StateTransition("state_3", "state_4", ["done"], "summarizing -> done"),
                # [Fix P0] Fallback early exit done
                StateTransition("state_1", "state_4", ["done"], "online -> done (early exit)"),
                StateTransition("state_2", "state_4", ["done"], "thinking -> done (early exit)"),
                StateTransition("state_1", "state_0", ["blocked"], "blocked -> reset"),
                StateTransition("state_2", "state_0", ["blocked"], "blocked -> reset"),
                StateTransition("state_3", "state_0", ["blocked"], "blocked -> reset"),
                StateTransition("state_0", "state_0", ["failed"], "any -> failed"),
                StateTransition("state_1", "state_0", ["failed"], "any -> failed"),
                StateTransition("state_2", "state_0", ["failed"], "any -> failed"),
                StateTransition("state_3", "state_0", ["failed"], "any -> failed"),
                StateTransition("state_1", "state_timeout", ["timeout"], "online -> timeout"),
                StateTransition("state_2", "state_timeout", ["timeout"], "thinking -> timeout"),
                StateTransition("state_3", "state_timeout", ["timeout"], "summarizing -> timeout"),
            ],
        )
        self._templates["thinking"] = thinking_template

        gate_template = PoolStateTemplate(
            pool_id="gate",
            initial_state="state_0",
            terminal_states={"state_3_approved", "state_3_rejected"},
            transitions=[
                StateTransition("state_0", "state_1", ["online"], "idle -> online"),
                StateTransition("state_1", "state_2", ["start_review"], "online -> reviewing"),
                StateTransition("state_2", "state_3_approved", ["approved"], "reviewing -> approved"),
                StateTransition("state_2", "state_3_rejected", ["rejected"], "reviewing -> rejected"),
                StateTransition("state_1", "state_0", ["blocked"], "blocked -> reset"),
                StateTransition("state_2", "state_0", ["blocked"], "blocked -> reset"),
            ],
        )
        self._templates["gate"] = gate_template

        construct_template = PoolStateTemplate(
            pool_id="construct",
            initial_state="state_0",
            terminal_states={"state_4", "state_timeout"},
            transitions=[
                StateTransition("state_0", "state_1", ["online"], "idle -> online"),
                StateTransition("state_1", "state_2", ["start_architecting"], "online -> architecting"),
                StateTransition("state_2", "state_3", ["start_finalizing"], "architecting -> finalizing"),
                StateTransition("state_3", "state_4", ["done"], "finalizing -> done"),
                # Fallback early exit done
                StateTransition("state_1", "state_4", ["done"], "online -> done (early exit)"),
                StateTransition("state_2", "state_4", ["done"], "architecting -> done (early exit)"),
                StateTransition("state_1", "state_0", ["blocked"], "blocked -> reset"),
                StateTransition("state_2", "state_0", ["blocked"], "blocked -> reset"),
                StateTransition("state_3", "state_0", ["blocked"], "blocked -> reset"),
                StateTransition("state_0", "state_0", ["failed"], "any -> failed"),
                StateTransition("state_1", "state_0", ["failed"], "any -> failed"),
                StateTransition("state_2", "state_0", ["failed"], "any -> failed"),
                StateTransition("state_3", "state_0", ["failed"], "any -> failed"),
                StateTransition("state_1", "state_timeout", ["timeout"], "online -> timeout"),
                StateTransition("state_2", "state_timeout", ["timeout"], "architecting -> timeout"),
                StateTransition("state_3", "state_timeout", ["timeout"], "finalizing -> timeout"),
            ],
        )
        self._templates["construct"] = construct_template

    def get_template(self, pool_id: str) -> PoolStateTemplate | None:
        return self._templates.get(pool_id)

    def register_template(self, template: PoolStateTemplate) -> None:
        """允许后续动态注册新池模板"""
        self._templates[template.pool_id] = template
