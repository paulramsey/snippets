package com.example.spanner;

import com.google.cloud.Timestamp;
import com.google.cloud.spanner.DatabaseClient;
import com.google.cloud.spanner.DatabaseId;
import com.google.cloud.spanner.Mutation;
import com.google.cloud.spanner.Spanner;
import com.google.cloud.spanner.SpannerOptions;
import com.google.cloud.spanner.Value;
import java.util.ArrayList;
import java.util.List;
import java.util.Random;

public class SpannerPopulate {

  static final String PROJECT_ID = "spanner-ns";
  static final String INSTANCE_ID = "dev-instance";
  static final String DATABASE_ID = "dev-db";
  static final String TABLE_NAME = "ns.test_table";

  public static void main(String[] args) {
    SpannerOptions options = SpannerOptions.newBuilder().setProjectId(PROJECT_ID).build();
    try (Spanner spanner = options.getService()) {
      DatabaseId db = DatabaseId.of(PROJECT_ID, INSTANCE_ID, DATABASE_ID);
      DatabaseClient dbClient = spanner.getDatabaseClient(db);

      List<Mutation> mutations = new ArrayList<>();
      Random random = new Random();

      System.out.println("Generating mutations...");
      // Looping logic: Perform 10 iterations
      for (int batch = 0; batch < 10; batch++) {
        // Collect 10,000 mutations to send in a single write operation
        for (int i = 0; i < 10000; i++) {
          mutations.add(
              Mutation.newInsertBuilder(TABLE_NAME)
                  // id (PK) is omitted to use DEFAULT (GENERATE_UUID())
                  // seq is omitted to use DEFAULT (BIT_REVERSE(SEQUENCE))
                  .set("col_a").to("Record " + (batch * 10000 + i))
                  .set("col_b").to(batch * 10000 + i)
                  .set("col_c").to(random.nextBoolean())
                  .set("last_updated").to(Value.COMMIT_TIMESTAMP)
                  .build());
        }
        // Write the batch of 10,000 mutations to Spanner
        Timestamp commitTimestamp = dbClient.write(mutations);
        System.out.printf("Wrote %d records at %s%n", mutations.size(), commitTimestamp.toString());
        mutations.clear();
      }

    } catch (Exception e) {
      e.printStackTrace();
    }
  }
}
