# Traces - Prerequisites
For the recording of a distributed trace, every involved component must propagate at least the trace context. For details, see [Trace Context](https://www.w3.org/TR/trace-context/#problem-statement).
- In Kyma, all modules involved in users’ requests support the [W3C Trace Context](https://www.w3.org/TR/trace-context) protocol. The involved Kyma modules are, for example, Istio, Serverless, and Eventing.
- Your application also must propagate the W3C Trace Context for any user-related activity. This can be achieved easily using the [Open Telemetry SDKs](https://opentelemetry.io/docs/instrumentation/) available for all common programming languages. If your application follows that guidance and is part of the Istio Service Mesh, it’s already outlined with dedicated span data in the trace data collected by the Kyma telemetry setup.
- Furthermore, your application must enrich a trace with additional span data and send these data to the cluster-central telemetry services. You can achieve this with [Open Telemetry SDKs](https://opentelemetry.io/docs/instrumentation/).