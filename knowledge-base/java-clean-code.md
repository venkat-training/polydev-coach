# Java Enterprise Clean Code & Best Practices

This knowledge base is used by the PolyDev Coach AI agents (running on Amazon Nova via
AWS Bedrock) for Java coaching. It is uploaded to Amazon S3 and indexed by Amazon Bedrock
Knowledge Bases for RAG retrieval by the Nova Lite Coach agent.

---

## 1. Error Handling

### Never Use Empty Catch Blocks
**Bad:**
```java
try {
    processData();
} catch (Exception e) {
    // silent failure — very dangerous
}
```

**Good:**
```java
try {
    processData();
} catch (DataProcessingException e) {
    log.error("Data processing failed | input={}", inputId, e);
    throw new ServiceException("Unable to process data", e);
}
```

**Reference:** Effective Java 3rd Ed. — Item 77: Don't ignore exceptions

### Use Specific Exception Types
**Bad:**
```java
catch (Exception e) { ... }  // Too broad
```

**Good:**
```java
catch (HttpClientErrorException e) {
    // Handle 4xx responses
} catch (HttpServerErrorException e) {
    // Handle 5xx responses
}
```

### Try-With-Resources
Always use try-with-resources for anything that implements `Closeable`:
```java
// Good: stream always closed
try (InputStream stream = connection.getInputStream()) {
    return parseResponse(stream);
}

// Good: DB resources always released
try (Connection conn = dataSource.getConnection();
     PreparedStatement stmt = conn.prepareStatement(SQL)) {
    stmt.setInt(1, userId);
    return stmt.executeQuery();
}
```

**Reference:** Effective Java 3rd Ed. — Item 9

---

## 2. Security

### Never Hardcode Credentials
**Bad:**
```java
private static final String DB_PASSWORD = "production_password_123";
```

**Good:**
```java
// Spring Boot — inject from application.properties / env vars
@Value("${db.password}")
private String dbPassword;
```

Or use a secrets manager (AWS Secrets Manager, HashiCorp Vault).

### Prevent SQL Injection
**Bad:**
```java
String query = "SELECT * FROM users WHERE id = " + userId;
stmt.execute(query);
```

**Good:**
```java
PreparedStatement stmt = conn.prepareStatement(
    "SELECT * FROM users WHERE id = ?"
);
stmt.setInt(1, userId);
```

---

## 3. Logging

### Use SLF4J (Never System.out or printStackTrace)
**Bad:**
```java
System.out.println("User found: " + user.getId());
e.printStackTrace();
```

**Good:**
```java
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

private static final Logger log = LoggerFactory.getLogger(UserService.class);

log.info("User found | userId={} | email={}", user.getId(), user.getEmail());
log.error("Failed to fetch user | userId={}", userId, exception);
```

### Use Parameterised Logging
```java
// Bad: string concatenation always executed even if DEBUG disabled
log.debug("Data: " + heavyObject.toString());

// Good: toString() only called if DEBUG is enabled
log.debug("Data: {}", heavyObject);
```

---

## 4. SOLID Principles

### Single Responsibility
Each class should have one reason to change:
```java
// Bad: does everything
class UserService {
    void createUser(...) { ... }
    String sendEmail(...) { ... }
    void logAudit(...) { ... }
}

// Good: each class has one job
class UserService   { void createUser(...) { ... } }
class EmailService  { String sendEmail(...) { ... } }
class AuditLogger   { void logAudit(...) { ... } }
```

### Dependency Inversion
Depend on abstractions, not implementations:
```java
// Bad: tightly coupled
class UserService {
    private MySQLUserRepository repo = new MySQLUserRepository();
}

// Good: injected, testable
class UserService {
    private final UserRepository repo;

    public UserService(UserRepository repo) {
        this.repo = repo;
    }
}
```

---

## 5. Performance

### StringBuilder in Loops
**Bad:**
```java
String result = "";
for (String item : items) {
    result += item;  // O(n²) — creates a new String each time
}
```

**Good:**
```java
StringBuilder sb = new StringBuilder();
for (String item : items) {
    sb.append(item);
}
String result = sb.toString();
```

### Use Optional Instead of Null Returns
```java
// Bad: caller doesn't know null is possible
public User findById(int id) {
    return userMap.get(id);  // May return null
}

// Good: explicit Optional
public Optional<User> findById(int id) {
    return Optional.ofNullable(userMap.get(id));
}

// Usage:
findById(42)
    .map(User::getName)
    .orElse("Unknown");
```

---

## 6. Concurrency

### Avoid Static Mutable State
**Bad:**
```java
public class UserCache {
    private static List<User> cache = new ArrayList<>();  // Not thread-safe!
}
```

**Good:**
```java
public class UserCache {
    private static final ConcurrentHashMap<Integer, User> cache = new ConcurrentHashMap<>();
}
```

### Use java.util.concurrent
Prefer `ExecutorService`, `CompletableFuture`, and `ConcurrentHashMap` over raw `Thread`
and `synchronized`.

---

## 7. Design Patterns

### Builder Pattern (for objects with many fields)
```java
User user = User.builder()
    .id(1)
    .name("Alice")
    .email("alice@example.com")
    .active(true)
    .build();
```

### Factory Pattern (for polymorphic creation)
```java
PaymentProcessor processor = PaymentProcessorFactory.create(PaymentMethod.CARD);
```

---

## 8. Clean Code Rules (Robert C. Martin)

| Rule | Description |
|------|-------------|
| Meaningful Names | `getUserById` not `getUBI` |
| Small Functions | Under 20 lines ideally |
| One Level of Abstraction | Don't mix high/low level logic in one function |
| No Magic Numbers | `MAX_RETRIES = 3` not `if (retries > 3)` |
| DRY | Don't Repeat Yourself — extract duplicated code |

---

## 9. Testing (JUnit 5 + Mockito)

```java
@ExtendWith(MockitoExtension.class)
class UserServiceTest {

    @Mock
    private UserRepository userRepository;

    @InjectMocks
    private UserService userService;

    @Test
    void shouldReturnUserWhenFound() {
        // Arrange
        User expectedUser = new User(1, "Alice");
        when(userRepository.findById(1)).thenReturn(Optional.of(expectedUser));

        // Act
        Optional<User> result = userService.findById(1);

        // Assert
        assertTrue(result.isPresent());
        assertEquals("Alice", result.get().getName());
        verify(userRepository).findById(1);
    }
}
```

**Reference:** JUnit 5 User Guide; Mockito Documentation

---

## 15. Secret Hygiene Note

All Java examples in this document must use non-sensitive placeholder strings only.
Do not include real credentials, JWTs, private keys, or production endpoints in documentation samples.

