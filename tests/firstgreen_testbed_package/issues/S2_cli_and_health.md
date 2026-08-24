# Add CLI version and health commit metadata

Make two user-facing improvements:

1. Add a `--version` option to the TinyShop CLI that prints the package version and exits successfully.
2. Add the current Git commit identifier to the health response. The value must be deterministic in tests and may use an injected environment variable or helper.

Add focused tests for both behaviors.
