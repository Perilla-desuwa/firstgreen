# ADR-004: Scheduler-owned deterministic verification

Status: Accepted

Worker completion only queues trusted verifier commands. Only a verifier pass followed by an
atomic database claim can make an attempt the winner and a task verified.

