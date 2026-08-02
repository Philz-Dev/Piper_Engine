import asyncio
import os 
import sys

# Ensure both project root and the shared directory are in Python's path
PROJECT_ROOT = os.path.abspath(os.path.dirname(__file__))
SHARED_ROOT = os.path.join(PROJECT_ROOT, "shared")

for path in [PROJECT_ROOT, SHARED_ROOT]:
    if path not in sys.path:
      sys.path.insert(0, path)

from shared.pipeline_executor import PipelineExecutor

MOCK_MANIFEST = {
    "pipeline": {
    "instructions": [
      {
        "execution": {
          "_args": {
            "name": "HubSpot_CRM_Search",
            "version": "1.2.0",
            "response_navigator": "results",
            "url": "https://api.hubapi.com/crm/v3/objects/contacts/search",
            "method": "POST",
            "class": {
              "authorization": "{{$env.Hubspot}}"
            },
            "headers": {
              "Authorization": "Bearer {authorization}",
              "Content-Type": "application/json"
            },
            "body": {
              "filterGroups": [
                {
                  "filters": [
                    {
                      "propertyName": "email",
                      "operator": "EQ",
                      "value": "$Typeform_webhook.form_response.answers.3.email"
                    }
                  ]
                }
              ],
              "sorts": [
                {
                  "propertyName": "createdate",
                  "direction": "DESCENDING"
                }
              ],
              "properties": [
                "firstname",
                "lastname",
                "email"
              ],
              "limit": 10,
              "after": 0
            }
          }
        },
        "execution_type": "service",
        "id": "hubspot_crm_search",
        "on_call": True,
        "service": {
          "app": "Hubspot",
          "action": "search",
          "type": "lib",
          "engine_internal": {}
        },
        "next_index": 1,
        "skip_index": 0,
        "index": 0
      },
      {
        "execution": {
          "timeout": 10,
          "_args": {
            "name": "HubSpot_CRM_Create_Contact",
            "response_navigator": "id",
            "url": "https://api.hubapi.com/crm/v3/objects/contacts",
            "method": "POST",
            "class": {
              "authorization": "{{$env.Hubspot}}"
            },
            "headers": {
              "Authorization": "Bearer {authorization}",
              "Content-Type": "application/json"
            },
            "body": {
              "properties": {
                "firstname": "{{$Typeform_webhook.form_response.answers.1.text | upper}} {{$Typeform_webhook.form_response.answers.1.text | upper }}",
                "lastname": "$Typeform_webhook.form_response.answers.4.text",
                "email": "$Typeform_webhook.form_response.answers.3.email",
                "phone": "$Typeform_webhook.form_response.answers.2.phone_number",
                "company": "rugar company",
                "website": "acme.ai",
                "lifecyclestage": "lead",
                "jobtitle": "Marketing Operations"
              }
            }
          }
        },
        "execution_type": "service",
        "id": "hubspot_create",
        "condition": [
          {
            "if": "0 == 0",
             "operations": [
            {
                "action": "call",
                "target": "telegram_bot"
               
            },
            {
                "action": "execute"
            }
            ]
          }
        ],
        "service": {
          "app": "Hubspot",
          "action": "create_contact",
          "type": "lib",
          "engine_internal": {}
        },
        "next_index": 2,
        "skip_index": 3,
        "index": 1
      },
      {
        "execution": {
          "_args": {
            "name": "telegram_bot_message",
            "method": "POST",
            "url": "https://api.telegram.org/bot{authorization}/sendMessage",
            "class": {
              "authorization": "$env.telegram_key"
            },
            "headers": {
              "Content-Type": "application/json"
            },
            "body": {
              "chat_id": "6878549543",
              "text": "New Lead Created in HubSpot!",
              "parse_mode": "HTML"
            }
          }
        },
        "execution_type": "service",
        "id": "telegram_bot",
        "service": {
          "app": "Telegram",
          "action": "alert",
          "type": "lib",
          "engine_internal": {}
        },
        "next_index": 3,
        "skip_index": 2,
        "index": 2
      },
      {
        "execution": {
          "_args": {
            "name": "hubspot_update_contact",
            "method": "PATCH",
            "url": "https://api.hubapi.com/crm/v3/objects/contacts/{contact_id}",
            "class": {
              "authorization": "{{$env.Hubspot}}",
              "contact_id": "$hubspot_crm_search.results.0.id"
            },
            "headers": {
              "Authorization": "Bearer {authorization}",
              "Content-Type": "application/json"
            },
            "body": {
              "properties": {
                "lifecyclestage": "lead",
                "hs_lead_status": "OPEN"
              }
            }
          }
        },
        "execution_type": "service",
        "id": "hubspot_update",
        "condition": [
          {
            "if": "0 == 0",
            "operations": [
              {
                "action": "call",
                "target": "hubspot_crm_search"
              }
            ]
          },
          {
            "if": "0 == 0",
            "operations": [
              {
                "action": "call",
                "target": "telegram_bot2"
              }
            ]
          },
          {
            "if": "0 == 0",
            "operations": [
              {
                "action": "goto",
                "target": "telegram_bot2"
              }
            ]
          }
        ],
        "operations": [
          {
            "action": "execute"
          }
        ],
        "service": {
          "app": "Hubspot",
          "action": "update_contact",
          "type": "lib",
          "engine_internal": {}
        },
        "next_index": 4,
        "skip_index": 5,
        "index": 3
      },
      {
        "execution": {
          "_args": {
            "name": "telegram_bot_message",
            "method": "POST",
            "url": "https://api.telegram.org/bot{authorization}/sendMessage",
            "class": {
              "authorization": "$env.telegram_key"
            },
            "headers": {
              "Content-Type": "application/json"
            },
            "body": {
              "chat_id": "6878549543",
              "text": "Update performed in HubSpot!",
              "parse_mode": "HTML"
            }
          }
        },
        "execution_type": "service",
        "id": "telegram_bot2",
        "service": {
          "app": "Telegram",
          "action": "alert",
          "type": "lib",
          "engine_internal": {}
        },
        "next_index": 5,
        "skip_index": 4,
        "index": 4
      }
    ],
    "id_map": {
      "hubspot_crm_search": 0,
      "hubspot_create": 1,
      "telegram_bot": 2,
      "hubspot_update": 3,
      "telegram_bot2": 4
    }
  }
}

class MockRegistry:
    def __init__(self):
        self.executor_map = {
            "service": self.mock_service_executor
        }

    async def mock_service_executor(self, **kwargs):
        await asyncio.sleep(0.01)
        return {"status": "completed", "output": "mock_script_success"}

class MockDB:
    def get_version(self, client_id):
        return "1_0"  # Or your default test version string

    def get_checkpoint(self, run_id):
        return None  # Return None to simulate a fresh run without prior checkpoints

    def update_live_logs(self, run_id, steps_snapshot):
        pass

    def finalize_log(self, run_id, status, steps_snapshot, error_msg):
        pass

    def save_checkpoint(self, run_id, checkpoint_data):
        pass

    def get_context(self, client_id, task_id, event_id=None):
        return {}

    def save_context(self, client_id, task_id, context, event_id=None):
        pass  # Add this method to mock saving context data

    def reschedule_after_completion(self, client_id, task_id):
        pass

async def main():
    executor = PipelineExecutor()
    executor.registry = MockRegistry()
    executor.db = MockDB()
    manifest = MOCK_MANIFEST["pipeline"]

    print("🚀 Starting linear pipeline test execution...")
    await executor.run_executor(
        manifest=manifest,
        event_id="linear_test_event",
        run_id="linear_test_run_01",
        task_id="linear_test_task",
        client_id="test_client",
        from_trigger=True,
        _crypto_engine=None,
        is_schedule=False
    )
    print("✅ Linear pipeline executed through all 8 sequential nodes successfully!")

if __name__ == "__main__":
    asyncio.run(main())