*This is a dedicated markdown about architecture view for fellow engineers education*.

Use **Hexagonal Architecture** (alternatively: Port-Adapter Architecture)
### Why?
since its goals are **maintainability** and **cross-platform**. Each module should be distinct and independence from each other to facilitate direct maintenance module-by-module rework in the future.

### Terminology
- **Core (Business Logic)**: Can only read from driving, and can only write to driven or observer
- **Driving (Primary)**: inputs
- **Driven (Secondary)**: outputs
- **Port**: header names, abstract classes
- **Adapter**: implementation
- **Observer**: In case driving adapter want to receive feedbacks
