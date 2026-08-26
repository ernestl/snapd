# Functional and integration tests

## Functional/integration tests

We write them using [spread](https://github.com/canonical/spread-plus). Generally all externally visible features and behaviour should have spread tests. It's also important to have them for robustness and fallback behaviour as related to system properties.

In order to keep the integration testing harness easy to read and consistent, there are some rules about the order and the existence of the different spread tests sections.

This is the ordered sections list to follow:
 1. summary (required)
 1. details (required)
 1. backends
 1. systems
 1. manual
 1. priority
 1. warn-timeout
 1. kill-timeout
 1. environment
 1. prepare
 1. restore
 1. debug
 1. execute (required)

The CI tooling will check and enforce the order and required sections when a spread test is created or updated.
