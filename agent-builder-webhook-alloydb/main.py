import json
import base64
import os

import functions_framework
from google.cloud.alloydb.connector import Connector
from langchain_core.prompts import PromptTemplate
from langchain_google_vertexai import VertexAI
import sqlalchemy
from tabulate import tabulate

# Define global variables for connection re-use.
pool = None

def exec_sql(sql, pool):
    # Run sql
    try:
        print(f"Running SQL query: {sql}")
        with pool.connect() as db_conn:

            # query database
            result = db_conn.execute(sqlalchemy.text(sql))

            # commit transaction (SQLAlchemy v2.X.X is commit as you go)
            db_conn.commit()
        
        return result

    except Exception as e:
        # Return error
        error_msg = {
            "status": "error",
            "message": "SQL Query Failed.",
            "details": str(e)
        }
        return error_msg

def format_sql_result_as_table(result):
    
    # Parse result
    rows = result.fetchall()
    column_names = result.keys()
    rowcount = result.rowcount

    # Format response as table
    if rows:
        table = tabulate(rows, headers=column_names, tablefmt="html")
        table = table.replace('<th>','<th style="min-width:100px;">')
    else:
        return "No results"

    # Ref:  https://cloud.google.com/dialogflow/cx/docs/reference/rest/v3/WebhookResponse
    #       https://cloud.google.com/dialogflow/cx/docs/reference/rest/v3/Fulfillment#ResponseMessage
    json_response = {
        "fulfillmentResponse":{
            "messages": [
                {
                    "payload": {
                        "richContent": [
                            [
                                {
                                    "type": "accordion",
                                    "title": "SQL Result",
                                    "subtitle": "SQL Result Details",
                                    "text": str(table)
                                }
                                
                            ]
                        ]
                    }
                }
            ],
            "merge_behavior": "APPEND"
        },
        "sessionInfo": {
            "parameters": {
                "rowCount": str(rowcount),
                "sqlResult": str(table),
            },
        },
    }

    return json_response


def format_error(result):
    _json_response = {
        "fulfillmentResponse": {
            "messages": [
                {
                    "payload": {
                        "richContent": [
                            [
                                {
                                    "type": "description",
                                    "title": "Error Generating SQL",
                                    "text": [
                                        result["message"],
                                        result["details"]  # Optionally include details
                                    ]
                                }
                            ]
                        ]
                    }
                }
            ],
            "merge_behavior": "APPEND"
        },
        "sessionInfo": {
            "parameters": {
                "rowCount": "0",  # Indicate no rows if there's an error
                "sql": "",      # Empty SQL in case of error
                "error": "true",
            },
        },
    }
    return _json_response


def exec_static_sql(request_json, pool):

    # Prep SQL statement
    sql = request_json["sessionInfo"]["parameters"]["sql"]
    
    # Run SQL
    result = exec_sql(sql, pool)

    # Check if error
    if isinstance(result, dict) and result.get("status") == "error":
        # Format result as error
        json_response = format_error(result)
    else:
        # Format result as table
        json_response = format_sql_result_as_table(result)
    
    return json_response


def exec_parameterized_sql(request_json, pool):
    # Build SQL statement
    sql_investment_search_phrase = request_json["sessionInfo"]["parameters"]["sql_investment_search_phrase"]
    print(f"Vector search phrase: {sql_investment_search_phrase}")
    
    sql = f"""
    SELECT ticker, etf, rating, overview, analysis,
    analysis_embedding <=> google_ml.embedding('textembedding-gecko@003', '{sql_investment_search_phrase}')::vector AS distance
    FROM investments
    ORDER BY distance
    LIMIT 5;
    """

    # Run SQL
    result = exec_sql(sql, pool)

    # Check if error
    if isinstance(result, dict) and result.get("status") == "error":
        # Format result as error
        json_response = format_error(result)
    else:
        # Format result as table
        json_response = format_sql_result_as_table(result)

    return json_response


def alloydb_webhook(request):
    """Responds to any HTTP request.
    Args:
        request (flask.Request): HTTP request object.
    Returns:
        The response text or any set of values that can be turned into a
        Response object using
        `make_response <http://flask.pocoo.org/docs/1.0/api/#flask.Flask.make_response>`.
    """
    
    # Declare pool as global to access and modify it
    global pool  
    
    # Load request JSON
    request_json = request.get_json()

    # Get webhook tag (query type)
    tag = request_json["fulfillmentInfo"]["tag"]
    print(f"Webhook tag: {tag}")

    # Environment Vars
    region = os.environ["REGION"]
    project_id = os.environ["PROJECT_ID"]

    # AlloyDB Vars
    cluster = os.environ["ALLOYDB_CLUSTER"]
    instance = os.environ["ALLOYDB_INSTANCE"]
    database = os.environ["ALLOYDB_DATABASE"]
    user = os.environ["ALLOYDB_USER"]
    password = os.environ["ALLOYDB_PASSWORD"]

    # Create sync connection pool if it doesn't exist
    connector = Connector()
    if pool is None:
        def getconn():
            conn = connector.connect(
                f"projects/{project_id}/locations/{region}/clusters/{cluster}/instances/{instance}",
                "pg8000",
                user=user,
                password=password,
                db=database,
            )
            return conn
        pool = sqlalchemy.create_engine(
            "postgresql+pg8000://",
            creator=getconn,
        )

    # Route request based on tag
    if tag == 'static':
        json_response = exec_static_sql(request_json, pool)
    elif tag == 'parameterized':
        json_response = exec_parameterized_sql(request_json, pool)
    else:
        raise Exception(f"Invalid tag: {tag}")

    # Returns json
    return json_response
