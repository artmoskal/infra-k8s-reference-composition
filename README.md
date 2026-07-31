# infra-k8s neutral composition reference

This repository owns the provider-neutral comprehensive fixture used to prove
the infra-k8s framework's external-consumer and target-portability boundary.

The reviewed Apps exercise multiple workloads, durable storage, typed secret
and config inputs, dependency-ordered idempotent bootstrap, public routing, a
protected admin path, and two controlled failure variants. They contain no
Target, provider, hostname, credential, or deployment-workhorse decision.

The separate private fleet repository owns the exact AppRelease revision,
Target bindings, effect approval, and lifecycle evidence. Production-like
operations always acquire one exact commit from this repository; local Compose
or operator state cannot change the declared plan.
