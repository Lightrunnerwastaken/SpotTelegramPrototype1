import logging
import os
from dataclasses import dataclass
from typing import Optional

try:
    # Boston Dynamics Spot SDK
    import bosdyn.client
    from bosdyn.client import create_standard_sdk
    from bosdyn.client.util import authenticate
    from bosdyn.client.lease import LeaseClient, LeaseKeepAlive
    from bosdyn.client.robot_state import RobotStateClient
    from bosdyn.client.robot_command import RobotCommandClient, RobotCommandBuilder, blocking_stand
    from bosdyn.client.power import PowerClient
    from bosdyn.client.graph_nav import GraphNavClient
    BOSDYN_AVAILABLE = True
except Exception:  # pragma: no cover - optional dependency
    BOSDYN_AVAILABLE = False

logger = logging.getLogger(__name__)


@dataclass
class SpotStatus:
    battery_percent: Optional[float]
    motor_power_state: str
    estop_status: str
    behavior_faults: int

    def summary(self) -> str:
        b = "?" if self.battery_percent is None else f"{self.battery_percent:.0f}%"
        return (
            f"🔋 {b}  |  ⚙️ {self.motor_power_state}  |  ⛔ {self.estop_status}  |  ⚠️ faults={self.behavior_faults}"
        )


class SpotController:
    def __init__(self, host: str, username: str, password: str) -> None:
        self.host = host
        self.username = username
        self.password = password
        self._robot = None
        self._lease_client = None
        self._state_client = None
        self._command_client = None
        self._power_client = None
        self._graphnav_client = None

    @classmethod
    def from_env(cls) -> Optional["SpotController"]:
        host = (os.getenv("SPOT_HOST") or "").strip()
        user = (os.getenv("SPOT_USERNAME") or "").strip()
        pwd = (os.getenv("SPOT_PASSWORD") or "").strip()
        if not host or not user or not pwd:
            return None
        return cls(host, user, pwd)

    def is_available(self) -> bool:
        return BOSDYN_AVAILABLE and bool(self.host)

    # --- Connection/bootstrap ---
    def _ensure_connected(self) -> None:
        if not BOSDYN_AVAILABLE:
            raise RuntimeError("bosdyn-client nicht installiert. Bitte 'pip install bosdyn-client' ausführen.")
        if self._robot is not None:
            return
        sdk = create_standard_sdk("spot-telegram-bot")
        robot = sdk.create_robot(self.host)
        try:
            robot.authenticate(self.username, self.password)
        except Exception:
            # Fallback zu interaktiver/utility-Auth falls konfiguriert
            authenticate(robot)
        robot.time_sync.wait_for_sync()

        self._robot = robot
        self._lease_client = robot.ensure_client(LeaseClient.default_service_name)
        self._state_client = robot.ensure_client(RobotStateClient.default_service_name)
        self._command_client = robot.ensure_client(RobotCommandClient.default_service_name)
        self._power_client = robot.ensure_client(PowerClient.default_service_name)
        try:
            self._graphnav_client = robot.ensure_client(GraphNavClient.default_service_name)
        except Exception:
            self._graphnav_client = None

    # --- Status ---
    def get_status(self) -> SpotStatus:
        self._ensure_connected()
        state = self._state_client.get_robot_state()

        # Battery percent
        pct = None
        try:
            # locomotion_charge_percentage is a google.protobuf.DoubleValue
            pct = float(state.power_state.locomotion_charge_percentage.value)
        except Exception:
            try:
                pct = float(state.battery_states[0].charge_percentage.value)
            except Exception:
                pct = None

        # Motor power state enum -> string
        try:
            motor_state = str(state.power_state.motor_power_state)
        except Exception:
            motor_state = "UNKNOWN"

        # E-Stop
        try:
            estop_ok = all(es.stop_level == es.ESTOP_LEVEL_NONE for es in state.estop_states)
            estop = "OK" if estop_ok else "ESTOP"
        except Exception:
            estop = "?"

        # Behavior faults
        try:
            faults = len(state.behavior_fault_state.faults)
        except Exception:
            faults = 0

        return SpotStatus(battery_percent=pct, motor_power_state=motor_state, estop_status=estop, behavior_faults=faults)

    def get_status_summary(self) -> str:
        try:
            return self.get_status().summary()
        except Exception as e:
            logger.warning(f"Spot Status fehlgeschlagen: {e}")
            return f"Spot Status nicht verfügbar: {e}"

    # --- Simple action: power on and stand ---
    def power_on_and_stand(self, timeout_sec: float = 20.0) -> str:
        self._ensure_connected()
        lease_keepalive = LeaseKeepAlive(self._lease_client, must_acquire=True, return_at_exit=True)
        try:
            self._power_client.power_on(timeout_sec=timeout_sec)
            blocking_stand(self._command_client, timeout_sec=10)
            return "Spot: powered on and standing."
        finally:
            lease_keepalive.__exit__(None, None, None)

    # --- GraphNav example: navigate to a waypoint id ---
    def navigate_to_waypoint(self, waypoint_id: str, cmd_duration_sec: float = 60.0) -> str:
        self._ensure_connected()
        if self._graphnav_client is None:
            raise RuntimeError("GraphNavClient nicht verfügbar. Ist GraphNav lizenziert/installiert?")
        lease_keepalive = LeaseKeepAlive(self._lease_client, must_acquire=True, return_at_exit=True)
        try:
            resp = self._graphnav_client.navigate_to(destination_waypoint_id=waypoint_id, command_duration=cmd_duration_sec)
            return f"GraphNav navigate_to gestartet: waypoint={waypoint_id}, resp.status={resp.status}"
        finally:
            lease_keepalive.__exit__(None, None, None)

