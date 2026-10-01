"""Runtime assembly for the trade-disabled FRLG remote data probe."""

from dataclasses import dataclass
import json

from pokeldn.frlg.link.host_app import HostApplication
from pokeldn.frlg.link.host_trade import HostTradeEngine
from pokeldn.frlg.remote.journal import JournalError, RemoteJournal
from pokeldn.frlg.remote.phase_gate import FilePhaseGate
from pokeldn.frlg.remote.policy import RemoteTradePolicy
from pokeldn.frlg.remote.transport import TransportError


@dataclass(frozen=True)
class RemoteAppConfig:
    profile: object
    ldn: object
    role: object
    plan: None = None


class RemoteProbeApplication(HostApplication):
    def __init__(self, config, lan_transport, *, log=print,
                 transport_factory=None, injector_factory=None, journal_root=None,
                 phase_gate: FilePhaseGate | None = None):
        self.lan_transport = lan_transport
        self.journal = RemoteJournal(lan_transport.run_id, root=journal_root)
        self.remote_policy = RemoteTradePolicy(
            lan_transport, log=getattr(log, "info", log), journal=self.journal,
            phase_gate=phase_gate)
        kwargs = {}
        if transport_factory is not None:
            kwargs["transport_factory"] = transport_factory
        if injector_factory is not None:
            kwargs["injector_factory"] = injector_factory
        super().__init__(config, log=log, activity_factory=self._make_activity, **kwargs)

    def _make_activity(self, *, profile, log):
        engine = HostTradeEngine(
            party=None, profile=profile, remote_policy=self.remote_policy,
            trust_pia=True, log=log)
        self.remote_policy.attach_engine(engine)
        return engine

    def _log_identity(self, _link_player):
        self.info(f"Local LDN discovery identity: {self.profile.discovery_name}; "
                  "game LinkPlayer and party data come from the local Switch.")
        self.info("P0 safety mode: real trade start, animation, save and commit are disabled.")

    def _hosting_instructions(self):
        return ("On the Switch choose Join Group for this local bridge. Use only a test save; "
                "the probe will refuse trade selection and never send START_TRADE.")

    def _rfu_ready_message(self):
        return "Local RFU link is ready; the P0 data exchange probe is active."

    def _completion_message(self):
        return "Local link closed; the P0 data probe ended without performing a trade."

    def _poll_control_events(self):
        if self.session is not None:
            self._activity().process_control()
        if self.remote_policy.journal_failure is None and self.journal.failure is not None:
            self.remote_policy.journal_failure = self.journal.failure
            self.info(f"P0 journal error: {self.journal.failure}; local RFU traffic remains active.")

    def _log_protocol_events(self, events):
        super()._log_protocol_events(events)
        if "connect" in events:
            self.remote_policy.local_link_state("connected")
        if "disconnect" in events:
            self.remote_policy.local_link_state("closed")

    def run(self):
        try:
            self.remote_policy.local_link_state("waiting")
            return super().run()
        finally:
            try:
                transport_error = self.lan_transport.error
                reason = ("link_failed" if self.remote_policy.failed is not None
                          or (transport_error is not None
                              and transport_error != "LAN peer disconnected")
                          or (self.session and not self._activity().close_confirmed)
                          else "cancelled")
                self.remote_policy.stop(reason)
                self.lan_transport.flush()
                # Process a peer stop and a queued EOF before taking the final snapshot.  This
                # makes the report reflect the control-plane order at normal asymmetric shutdown.
                self.remote_policy.poll()
                report = self.remote_policy.report()
                if self.remote_policy.engine is not None:
                    report["p0_command_audit"] = self.remote_policy.engine.p0_command_audit()
                    report["local_close_confirmed"] = self.remote_policy.engine.close_confirmed
                self.journal.append("probe_summary", **report)
                self.info("P0 probe summary: " + json.dumps(report, sort_keys=True))
            except (TransportError, JournalError, OSError) as exc:
                self.info(f"Could not record final LAN probe status: {exc}")
            try:
                self.journal.close()
            except JournalError as exc:
                self.info(str(exc))
            self.lan_transport.close()
