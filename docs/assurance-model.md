# Assurance model

WorldState Check separates an action from evidence that the requested outcome exists.

```text
intent -> action -> acknowledgement -> independent observation -> postconditions -> verdict
```

An acknowledgement is evidence that a command or tool call was accepted. It is not, by itself, evidence that the requested state change occurred.

## Verdicts

- `VERIFIED`: every required postcondition was observed and passed.
- `NOT_VERIFIED`: at least one required postcondition was observed and failed.
- `UNCERTAIN`: no required postcondition failed, but at least one required postcondition could not be evaluated reliably.

Optional checks are reported but do not block a verified verdict.

## Evidence independence

The strongest checks observe state independently of the component that initiated the action. Examples include a health endpoint after deployment, telemetry after a spacecraft mode command, a sensor measurement after physical maintenance, or a database row after an agent claims a transaction completed.

The tool does not prove that an observation source is truthful. Sensor trust, cryptographic attestation, calibration, identity, and Byzantine fault tolerance are separate assurance problems.
