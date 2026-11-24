50 golden questions over 3807 chunks, latency over 3 run(s) per question, model inference included.

| Variant | Recall@1 | Recall@5 | MRR | p50 ms | p95 ms |
|---|---|---|---|---|---|
| vector | 0.74 | 0.92 | 0.82 | 136 | 333 |
| keyword | 0.48 | 0.52 | 0.50 | 4 | 18 |
| hybrid | 0.74 | 0.92 | 0.83 | 183 | 458 |

Recall@5 by question kind, hybrid:

| Kind | Recall@5 |
|---|---|
| error | 1.00 |
| howto | 0.89 |
| identifier | 1.00 |
| limit | 0.88 |
| param | 0.88 |

Not in the top 5 for hybrid:

- param-pg-idle-in-transaction: rank 6
- limit-oom: rank 15
- howto-clickhouse-cli: rank none
- howto-keystore: rank 10

Rank of the expected page per question (none = not in the top 20):

| Question | vector | keyword | hybrid |
|---|---|---|---|
| param-kafka-connect-private | 2 | none | 2 |
| param-kafka-message-max-bytes | 1 | none | 1 |
| param-kafka-log-retention-hours | 1 | none | 1 |
| param-redis-maxmemory-policy | 2 | 1 | 1 |
| param-pg-idle-in-transaction | 6 | none | 6 |
| param-kafka-auto-create-topics | 1 | none | 1 |
| param-pg-statement-timeout | 1 | none | 1 |
| param-opensearch-index-retention | 2 | none | 2 |
| limit-pg-connections-plan | 1 | none | 2 |
| limit-mysql-connections | 1 | none | 1 |
| limit-redis-connections | 1 | none | 2 |
| limit-backup-retention | 1 | none | 1 |
| limit-clickhouse | 1 | none | 2 |
| limit-pg-idle-connections | 2 | none | 2 |
| limit-oom | 15 | none | 15 |
| limit-kafka-full-disk | 1 | none | 1 |
| howto-kafka-cli-topic-retention | 1 | 1 | 1 |
| howto-kafka-change-retention | 1 | 1 | 1 |
| howto-pg-read-replica | 1 | 2 | 1 |
| howto-ca-cert | 1 | 1 | 1 |
| howto-auth-token | 1 | 1 | 1 |
| howto-add-storage | 1 | none | 1 |
| howto-kafka-acls | 1 | 1 | 1 |
| howto-kafka-sasl | 1 | 3 | 1 |
| howto-pg-extensions | 1 | none | 3 |
| howto-pg-dump-restore | 1 | 1 | 1 |
| howto-kcat | 1 | none | 1 |
| howto-clickhouse-cli | none | none | none |
| howto-opensearch-low-disk | 1 | none | 2 |
| howto-keystore | 4 | none | 10 |
| howto-pg-slow-queries | 1 | none | 1 |
| howto-flink-sql-app | 1 | 1 | 1 |
| howto-disk-autoscaler | 1 | 1 | 1 |
| howto-redis-overcommit | 1 | 1 | 1 |
| ident-message-max-bytes | 1 | 1 | 1 |
| ident-log-retention-hours | 1 | 1 | 1 |
| ident-redis-maxmemory | 2 | 1 | 1 |
| ident-idle-in-transaction | 2 | none | 2 |
| ident-retention-ms | 1 | 1 | 1 |
| ident-pg-stat-statements | 1 | 1 | 1 |
| ident-statement-timeout | 1 | 1 | 1 |
| ident-overcommit-memory | 1 | 1 | 1 |
| ident-kafka-connect-private-access | 1 | 1 | 1 |
| ident-max-connections-pg | 3 | 1 | 1 |
| error-not-leader-for-partition | 1 | none | 1 |
| error-failed-to-update-metadata | 11 | 1 | 1 |
| error-replication-slot-active | 5 | 1 | 1 |
| error-superuser-publication | 1 | 1 | 1 |
| error-owner-of-extension | 1 | 1 | 1 |
| error-member-of-role-terminated | 1 | 1 | 1 |
