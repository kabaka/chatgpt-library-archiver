---
name: archiver-adr-workflow
description: Architecture Decision Record creation workflow for chatgpt-library-archiver using the MADR 4.0.0 template — when to create ADRs, numbering, status transitions, and decision documentation best practices
---

# ADR Workflow for ChatGPT Library Archiver

Architecture Decision Record creation process using the MADR (Markdown Any Decision Records) 4.0.0 template. Use this skill when creating, reviewing, or managing ADRs.

**When to use this skill:**
- Creating a new ADR
- Deciding whether a change warrants an ADR
- Understanding ADR status lifecycle
- Reviewing an existing ADR for completeness

## When to Create an ADR

**Definitely needs an ADR:**
- Technology or library choices (image processing library, API client, gallery framework)
- Storage format decisions (metadata schema, thumbnail layout, gallery structure)
- CLI interface changes that affect user workflows
- Security model decisions (credential storage, download validation)
- Patterns that affect multiple modules (error handling, concurrency model, status reporting)

**Does NOT need an ADR:**
- Bug fixes, minor refactoring, configuration tweaks
- Implementation details within a single function or module
- Test-only changes

## ADR Creation Process

### 1. Choose the Next Number

Check `docs/adr/` for the highest existing number. Use the next sequential number.

**Filename format**: `docs/adr/NNNN-title-in-kebab-case.md`

### 2. Write Using the MADR 4.0.0 Template

```markdown
# [Short Title of Solved Problem or Solution]

Date: YYYY-MM-DD

## Status

Proposed

## Context

[Describe the problem. What issue are we facing? What constraints exist?]

## Decision Drivers

* [Driver 1, e.g., simplicity, performance, security]
* [Driver 2]

## Considered Options

* [Option 1]
* [Option 2]
* [Option 3]

## Decision Outcome

Chosen option: "[Option N]", because [justification].

### Consequences

* Good, because [positive consequence]
* Bad, because [negative consequence]

### Confirmation

[How will we verify this decision was correct? What metrics or observations?]

## Pros and Cons of the Options

### [Option 1]

* Good, because [argument]
* Bad, because [argument]

### [Option 2]

* Good, because [argument]
* Bad, because [argument]

## More Information

[Links to related ADRs, external resources, issues]
```

### 3. Update the ADR Index

Add an entry to `docs/adr/README.md`:

```markdown
- [ADR-NNNN](NNNN-title.md) - Short description of the decision
```

### 4. Set Appropriate Status

| Status | When |
|--------|------|
| **Proposed** | During initial creation and review |
| **Accepted** | When merged to main branch |
| **Deprecated** | No longer recommended but not replaced |
| **Superseded by [ADR-XXXX]** | Replaced by a newer decision |

## Writing Tips

1. **Context**: Explain the problem for someone who wasn't there. Include technical constraints and business requirements.
2. **Decision Drivers**: Be explicit about what matters most. Is it simplicity? Performance? Security? Maintainability?
3. **Alternatives**: Always list at least 2 genuine alternatives. Include "do nothing" if applicable.
4. **Consequences**: Be honest about downsides. Every decision has trade-offs.
5. **Confirmation**: Define how you'll know the decision was right (or wrong).

## Quality Checklist

- [ ] Title clearly names the decision (not the problem)
- [ ] Context explains the problem without assuming reader knowledge
- [ ] At least 2 alternatives genuinely considered
- [ ] Decision outcome states the choice AND the justification
- [ ] Both positive and negative consequences documented
- [ ] Confirmation criteria are specific and measurable
- [ ] Cross-references to related ADRs included
- [ ] ADR index updated

## References

- [MADR 4.0.0 Template](https://github.com/adr/madr/blob/4.0.0/template/adr-template.md)
- [ADR GitHub Organization](https://adr.github.io/)
