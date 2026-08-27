from stretis import PiperSDK, InMemoryCredentialStore
import asyncio

async def main():
    # 1. Set up store and seed credentials
    store = InMemoryCredentialStore()
    store.save_bundle("client_temp", "asana", {"access_token": "mock_token"}) # add real user credentials this mock up is only ue for example

    # 2. Build the request (yields inert {{$cred...}} markers)
    sdk = PiperSDK(store=store)

    built_request = sdk.build_schema(
        tenant_id="client_temp",
        app="asana",
        action="addcustomfieldsettingforgoal",

        # field value mock up example repalce it with real field
        field_values={
            "class.goal_gid": "12345",
            "class.opt_pretty": True,  # Added required query parameter
            "body.data.custom_field": "123456789",
            "body.data.is_important": True,
            "body.data.insert_before": "none",
            "body.data.insert_after": "none"
        }
    )
    
    # this is only if you want to use the sdk's executor, you can alwys wire your own executor after the schema is built here inplace of the sdk's executor but also note to be able to use the PiperSdk's executor, you will have to install some dependency the executor relies on [https, tenacity]
    # 4. Dispatch the request asynchronously
    # This hydrates the credentials in memory, applies rate limits, 
    # handles retries on 429/5xx errors, and executes the call.
    result = await sdk.dispatch(
        tenant_id="client_temp",
        app="asana",
        request=built_request
    )

    if result.status == "success":
        print("API Call Succeeded:", result.data)
    else:
        print("API Call Failed:", result.error)

# Run the async loop
asyncio.run(main())