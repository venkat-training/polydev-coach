# MuleSoft Integration Best Practices

This knowledge base is used by the PolyDev Coach AI agents (running on Amazon Nova via
AWS Bedrock) to provide accurate, reference-backed coaching on MuleSoft integration patterns.
It is uploaded to Amazon S3 and indexed by Amazon Bedrock Knowledge Bases for RAG retrieval
by the Nova Lite Coach agent.

---

## 1. Error Handling

### Always Define Error Handlers
Every flow that performs external calls MUST have an On Error handler.

**Bad:**
```xml
<flow name="getUserFlow">
  <http:request config-ref="HTTP_Config" method="GET" path="/users"/>
</flow>
```

**Good:**
```xml
<flow name="getUserFlow">
  <http:request config-ref="HTTP_Config" method="GET" path="/users"/>
  <error-handler>
    <on-error-propagate type="HTTP:CONNECTIVITY">
      <logger level="ERROR" message="HTTP connection failed: #[error.description]"/>
      <raise-error type="APP:EXTERNAL_SERVICE_DOWN" description="Downstream service unavailable"/>
    </on-error-propagate>
    <on-error-continue type="ANY">
      <logger level="ERROR" message="Unexpected error: #[error.description]"/>
      <set-payload value='{"error": "Internal error", "correlationId": "#[correlationId]"}'/>
    </on-error-continue>
  </error-handler>
</flow>
```

**Reference:** MuleSoft Docs — Error Handling in Mule 4

### On Error Propagate vs On Error Continue
- **on-error-propagate**: Re-throws the error after executing. Use for fatal errors.
- **on-error-continue**: Swallows the error and continues. Use for recoverable conditions.

---

## 2. Configuration Externalisation

### Never Hardcode Values
All environment-specific values MUST be in `.properties` files referenced via `${property.key}`.

**Bad:**
```xml
<db:config name="DB_Config">
  <db:my-sql-connection host="prod-db.company.com"
                        user="admin" password="prod_password_123"/>
</db:config>
```

**Good:**
```xml
<db:config name="DB_Config">
  <db:my-sql-connection host="${db.host}"
                        user="${db.user}" password="${secure::db.password}"/>
</db:config>
```

With `config/dev.yaml`:
```yaml
db:
  host: localhost
  user: devuser
  password: devpassword
```

**Reference:** MuleSoft Docs — Configuring Properties

### Secure Properties
Use `${secure::property.name}` for passwords and secrets. Configure the Secure Properties module
with a master key passed as a system property at runtime — never hardcoded.

---

## 3. Flow Design

### Flow Naming Conventions
- Use **camelCase** for flow names: `getUserByIdFlow`, `processOrderSubFlow`
- Suffix flows with `Flow` and sub-flows with `SubFlow`
- Name error handlers: `getUserByIdFlow-error-handler`

### Flow Complexity Limits
| Component | Recommended Limit |
|-----------|------------------|
| Flows per application | ≤ 100 |
| Components per flow | ≤ 15 |
| Sub-flows per application | ≤ 50 |

Flows exceeding these limits become hard to test and maintain.

### Decompose Large Flows
Extract reusable logic into sub-flows:
```xml
<sub-flow name="validatePayloadSubFlow">
  <!-- validation logic here -->
</sub-flow>

<flow name="createOrderFlow">
  <http:listener .../>
  <flow-ref name="validatePayloadSubFlow"/>
  <!-- business logic -->
</flow>
```

---

## 4. Logging

### Use Correct Log Levels
| Level | When to Use |
|-------|-------------|
| ERROR | Exceptions, failures requiring human intervention |
| WARN  | Unexpected but handled conditions |
| INFO  | Key business events (entry/exit of flows, important milestones) |
| DEBUG | Developer details — **NEVER in production** |

**Bad:**
```xml
<logger level="DEBUG" message="Payload: #[payload]"/>
```

**Good:**
```xml
<logger level="INFO"
        message="Order created | orderId=#[payload.orderId] | correlationId=#[correlationId]"
        category="com.company.orders"/>
```

### Always Include Correlation ID
```xml
<logger level="INFO"
        message="Processing request | correlationId=#[correlationId] | path=#[attributes.requestPath]"/>
```

### Avoid Logging Sensitive Data
Never log: passwords, API keys, credit card numbers, PII (names, emails, SSNs).

---

## 5. Orphaned Flow Detection

An orphaned flow is one that:
- Is not referenced by any `<flow-ref>` in the application
- Is not triggered by an event source (HTTP listener, scheduler, etc.)
- Is not a global error handler

Orphaned flows waste memory and confuse developers. Remove them or add a comment explaining
why they exist. The mulesoft_package_validator detects these automatically.

---

## 6. APIkit & RAML

### Always Use APIkit Router
When building API-led connectivity, use the APIkit router to validate incoming requests
against your RAML spec automatically:

```xml
<apikit:router config-ref="api-config"/>
```

### RAML Best Practices
- Define all responses (200, 400, 404, 500) in your RAML
- Use `!include` for reusable data types
- Version your API in the RAML: `version: v1`

---

## 7. DataWeave

### Avoid Heavy Transformations in Flows
Move complex DataWeave scripts to separate `.dwl` files:
```xml
<ee:transform doc:name="Transform Payload">
  <ee:message>
    <ee:set-payload resource="dw/transformOrder.dwl"/>
  </ee:message>
</ee:transform>
```

### Null Safety
Always use the `default` operator:
```dataweave
payload.customer.email default "unknown@example.com"
```

---

## 8. Security Scanning Rules

The mulesoft_package_validator (integrated into PolyDev Coach) checks for:

| Rule | Severity | Description |
|------|----------|-------------|
| MULE-SECURITY | CRITICAL | Hardcoded password/API key in XML or YAML |
| MULE-ORPHAN-FLOW | WARNING | Unreferenced flow |
| MULE-FLOW-NAMING | WARNING | Non-camelCase flow names |
| MULE-DEBUG-LOG | WARNING | DEBUG logger in production flow |
| MULE-CONFIG | WARNING | Missing mandatory config file |
| MULE-UNUSED-DEP | INFO | Unused Maven dependency |

---

## 9. Performance

- **Connection Pooling**: Configure max-pool-size on DB and HTTP connectors
- **Timeout Configuration**: Always set `responseTimeout` on HTTP requestors
- **Batch Processing**: Use `<batch:job>` for bulk record processing — never loop with
  `<foreach>` over thousands of records
- **Object Store**: Use persistent Object Store for state that must survive restarts
- **Async Processing**: Use `<async>` scope for fire-and-forget operations that don't
  need a response

---

## 13. Secret Hygiene Note

All MuleSoft XML/YAML snippets in this guide must remain example-only and non-sensitive.
Use placeholders for usernames/passwords and never include live secure-property keys or encrypted blobs from production environments.

