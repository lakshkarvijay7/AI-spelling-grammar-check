def format_response(errors):
    return {
        "status": True,
        "response": {
            "errors": errors
        }
    }