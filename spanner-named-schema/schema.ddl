CREATE SCHEMA ns;
CREATE SEQUENCE my_seq OPTIONS (sequence_kind = 'bit_reversed_positive');
CREATE TABLE ns.test_table (
  id STRING(36) DEFAULT (GENERATE_UUID()),
  seq INT64 DEFAULT (BIT_REVERSE(GET_NEXT_SEQUENCE_VALUE(SEQUENCE my_seq), true)),
  col_a STRING(MAX),
  col_b INT64,
  col_c BOOL,
  last_updated TIMESTAMP OPTIONS (allow_commit_timestamp=true),
) PRIMARY KEY (id);
