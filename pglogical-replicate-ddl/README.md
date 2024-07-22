# Use pglogical trigger to replicate DDL

The [pglogical docs](https://github.com/2ndQuadrant/pglogical) show how to [create a trigger](https://github.com/2ndQuadrant/pglogical#automatic-assignment-of-replication-sets-for-new-tables) to automatically add a new table to a replication set, but this only replicates DML, not DDL. The docs also show how to create new objects on the provider via the [pglogical.replicate_ddl_command()](https://github.com/2ndQuadrant/pglogical?tab=readme-ov-file#additional-functions) function, but this function requires devs/DBAs to know about it and always use it - i.e. if they accidentally create new tables outside of that function, they would end up with tables that don't get replicated (a very error-prone process).

In this snippet, I modified the trigger from the pglogical docs to replicate DDL via replicate_ddl_command(current_query()). This convenience comes with two requirements:

1. You must create tables idempotently (i.e. with IF NOT EXISTS). Otherwise, you will see a misleading "table already exists" error if you try to create a table without this (and the table will not be created). This is because the replicate_ddl_command() function executes the command on the provider first and then replicates it to the subscriber, but the command has already (and necessarily) run once on the provider before the trigger fires.
1. You must define the schema in your CREATE table command, otherwise you will get an error saying that you haven't specified a schema, and the change will be rolled back.

Create the trigger, then test by creatinga  new table and adding some data, like:

```sql
CREATE TABLE IF NOT EXISTS public.test_table_2 (col1 INT PRIMARY KEY);
INSERT INTO test_table_2 VALUES (1),(2),(3);
```