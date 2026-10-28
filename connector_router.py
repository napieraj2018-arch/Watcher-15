"""Safe routing hints: use a connected ChatGPT app before Steel browser login.

This is a READ-ONLY declarative planner. It has NO access to ChatGPT plugins,
OAuth tokens, Steel cookies, private task history or customer accounts.
The ChatGPT agent MUST recheck the actual connector, account identity,
action schema and content material before taking any action. A route hint
never authorizes publication, confirms authentication or submits a form.
"""
from __future__ import annotations

from copy import deepcopy
from verification_status import email_confirmation_plan

ROUTER_VERSION = "2026-10-28.1"
BRANDS = frozenset(("", "anita", "weterynarz", "nkw", "aibrowser"))
SERVICES = frozenset((
    "instagram", "facebook", "gmail", "wordpress", "google_business",
    "windsor", "metricool", "browser",
    "youtube", "google_search_console", "github", "render", "google_drive",
))
OPERATIONS = frozenset((
    "read", "post", "image_post", "reel", "story", "carousel",
    "highlights", "reviews", "email_read", "email_draft", "email_send", "email_verify",
    "wordpress_read", "wordpress_draft", "wordpress_publish",
    "business_reviews", "business_post", "analytics",
    "video_read", "video_update", "thumbnail_update", "video_upload", "channel_analytics",
    "search_analytics", "url_inspect", "issue_read", "pr_read", "pr_create",
    "service_status", "deploy_history", "deploy", "file_search", "file_metadata",
))
BRAND_TARGET = {
    "anita": {
        "instagram": "17841400064953151",
        "facebook": "1630317700539552",
        "google_business": "locations/17588627068282939119",
        "wordpress": "https://architekt.radom.pl/poradnik",
        "browser_meta": "Meta - Anita",
        "browser_google": "Google - Architekt",
    },
    "weterynarz": {
        "instagram": "not_verified",
        "facebook": "138554046242234",
        "google_business": "locations/10098883123027920088",
        "wordpress": "https://weterynarz.radom.pl",
        "browser_meta": "Meta - Maciej - Monitoring",
        "browser_google": "Google - Weterynarz",
    },
}

# Operations advertised by the connected ChatGPT plugins when inspected.
# DO NOT imply a profile is authenticated until current account readback.
API_ROUTE = {
    ("instagram", "read"): ("Windsor_ai", "instagram", "get_data",
                              ("verified_account_id", "supported_fields")),
    ("facebook", "read"): ("Windsor_ai", "facebook_organic", "get_data",
                             ("verified_page_id", "supported_fields")),
    ("google_business", "read"): ("Windsor_ai", "google_my_business", "get_data",
                                    ("verified_location_id", "supported_fields")),
    ("instagram", "reel"): ("Windsor_ai", "instagram", "create_video_post",
                            ("public_https_video_url", "caption_optional")),
    ("instagram", "image_post"): ("Windsor_ai", "instagram", "create_image_post",
                                  ("public_https_jpeg_url", "caption_optional")),
    ("instagram", "carousel"): ("Windsor_ai", "instagram", "create_carousel_post",
                                 ("two_to_ten_public_https_images",)),
    ("instagram", "story"): ("Windsor_ai", "instagram", "create_story",
                             ("public_https_image_or_video_url",)),
    ("facebook", "post"): ("Windsor_ai", "facebook_organic", "create_post",
                            ("message_or_link",)),
    ("facebook", "image_post"): ("Windsor_ai", "facebook_organic", "create_photo_post",
                                  ("image_upload_and_photo_id",)),
    ("gmail", "email_read"): ("Gmail", "gmail", "search_emails",
                              ("current_mailbox_identity",)),
    ("gmail", "email_verify"): ("Gmail", "gmail", "search_email_ids",
                                ("verified_mailbox_link", "exact_recipient",
                                 "authorized_current_confirmation_flow", "challenge_start_time")),
    ("gmail", "email_draft"): ("Gmail", "gmail", "create_draft",
                               ("recipient_subject_body",)),
    ("gmail", "email_send"): ("Gmail", "gmail", "send_email",
                              ("recipient_subject_body",)),
    ("wordpress", "wordpress_read"): ("WPVibe", "wordpress", "site_info",
                                       ("verified_site_url",)),
    ("wordpress", "wordpress_draft"): ("WPVibe", "wordpress", "discover_abilities",
                                        ("site_url", "draft_content")),
    ("wordpress", "wordpress_publish"): ("WPVibe", "wordpress", "discover_abilities",
                                          ("site_url", "approved_post_content")),
    ("google_business", "business_reviews"):
        ("Windsor_ai", "google_my_business", "get_data",
         ("verified_location_id", "review_id_and_text")),
    ("google_business", "business_post"):
        ("Windsor_ai", "google_my_business", "create_local_post",
         ("verified_location_id", "post_content")),
    ("windsor", "analytics"): ("Windsor_ai", "selected_connector", "get_data",
                                ("verified_account_id", "selected_fields")),
    ("metricool", "analytics"): ("Metricool", "selected_brand", "getAnalyticsDataByMetrics",
                                  ("verified_brand_id",)),
    # Direct account connectors are hints only; none of these routes grants
    # an API token, starts a browser, signs in or changes remote content.
    ("youtube", "video_read"): ("vidIQ", "youtube", "vidiq_get_videos_by_ids",
                                 ("verified_channel_id", "video_ids")),
    ("youtube", "channel_analytics"): ("vidIQ", "youtube", "vidiq_channel_analytics",
                                        ("verified_channel_id", "date_range")),
    ("youtube", "video_update"): ("vidIQ", "youtube", "vidiq_update_video",
                                   ("verified_channel_id", "video_id", "approved_metadata")),
    ("youtube", "thumbnail_update"): ("vidIQ", "youtube", "vidiq_update_video_thumbnail",
                                       ("verified_channel_id", "video_id", "approved_thumbnail")),
    ("youtube", "video_upload"): ("vidIQ", "youtube", "vidiq_video_upload",
                                   ("verified_channel_id", "approved_media_source", "metadata")),
    ("google_search_console", "search_analytics"):
        ("GSC_Wizard", "search_console", "query_search_analytics",
         ("verified_property", "date_range", "dimensions")),
    ("google_search_console", "url_inspect"):
        ("GSC_Wizard", "search_console", "inspect_url",
         ("verified_property", "exact_page_url")),
    ("github", "issue_read"): ("GitHub", "repository", "fetch_issue",
                                ("verified_repo", "issue_number")),
    ("github", "pr_read"): ("GitHub", "repository", "fetch_pr",
                             ("verified_repo", "pr_number")),
    ("github", "pr_create"): ("GitHub", "repository", "create_pull_request",
                               ("verified_repo", "reviewed_head_and_base", "approved_diff")),
    ("render", "service_status"): ("Render", "web_service", "get_service",
                                    ("verified_workspace_id", "verified_service_id")),
    ("render", "deploy_history"): ("Render", "web_service", "list_deploys",
                                    ("verified_workspace_id", "verified_service_id")),
    ("render", "deploy"): ("Render", "web_service", "trigger_deploy",
                            ("verified_workspace_id", "verified_service_id",
                             "accepted_exact_commit", "idle_provider_gate")),
    ("google_drive", "file_search"): ("Google_Drive", "drive", "search",
                                       ("verified_drive_scope", "query")),
    ("google_drive", "file_metadata"): ("Google_Drive", "drive", "get_file_metadata",
                                         ("verified_drive_scope", "file_id")),
}

# Explicitly unsupported by the currently verified connector action schema.
# Never silently substitute a photo/video post for the requested media type.
NO_VERIFIED_API = frozenset((
    ("instagram", "highlights"),
    ("facebook", "reel"),
    ("facebook", "story"),
))
WRITES = frozenset((
    "post","image_post","reel","story","carousel","email_send",
    "email_draft","wordpress_draft","wordpress_publish","business_post",
    "video_update","thumbnail_update","video_upload","pr_create","deploy",
))

# Reuse the current catalogue for generic reads; do not invent new write aliases.
READ_ALIASES = {
    ("gmail", "read"): "email_read",
    ("wordpress", "read"): "wordpress_read",
    ("google_business", "reviews"): "business_reviews",
}

# Advisory classification only. Observations are not authorization evidence;
# the executing agent must confirm the actual provider response and account.
ACCESS_RECOVERY = {
    "empty_result": "check_query_scope_and_data_freshness",
    "transport_error": "bounded_read_retry_without_reauthentication",
    "rate_limited": "respect_provider_retry_after_without_reauthentication",
    "permission_denied": "verify_exact_account_and_operation_scope",
    "unknown_error": "inspect_sanitized_error_without_assuming_logout",
    "provider_reauthorization_required": "confirm_provider_evidence_then_authorize_affected_connection",
    "human_verification_required": "pause_affected_step_for_human_verification",
    "browser_quarantined": "independent_provider_reconciliation_no_browser_restart",
    "write_outcome_unknown": "verify_receipt_or_existing_object_before_any_retry",
}


def plan_access_recovery(observation: str) -> dict:
    """Return bounded recovery guidance, not authority to log in or resubmit.

    No network, credentials, provider objects or customer data are accepted.
    A permission error or empty response is never proof of revoked login.
    """
    if type(observation) is not str or observation not in ACCESS_RECOVERY:
        return {"status": "unsupported_observation", "login_attempted": False}
    return {
        "status": "advisory_only",
        "next_step": ACCESS_RECOVERY[observation],
        "authentication": "unknown",
        "requires_trusted_provider_evidence": True,
        "reauthorization_may_be_needed": observation == "provider_reauthorization_required",
        "independent_connector_tasks_may_continue": True,
        "retry_write_allowed": False,
        "clear_quarantine_allowed": False,
        "login_attempted": False,
    }


def plan_operation(service: str, operation: str, brand: str = "") -> dict:
    """Return safe, public, non-authoritative route information.

    Unknown requests and ambiguous account choices fail closed.
    This tool NEVER publishes and does not accept content, URLs or secrets.
    """
    if service == 'facebook' and isinstance(operation,str) and operation.casefold().startswith('użyj konta meta '):
        from meta_command import parse_command, MetaCommandError
        try:
            return {**parse_command(operation), 'status':'private_meta_preview_workflow_required',
                    'binding_source':'current_owner_private_checkpoint',
                    'browser_started':False, 'published':False,
                    'next_step':'Resolve alias in private registry; verify identity and exact group; freeze ordered permalink, show preview, require exact approval, journal once, verify receipt.'}
        except MetaCommandError as exc:
            return {'status':'unsupported_request','error':str(exc),'browser_started':False,'published':False}
    if (type(service) is not str or type(operation) is not str
        or type(brand) is not str or service not in SERVICES
        or operation not in OPERATIONS or brand not in BRANDS):
        return {"status":"unsupported_request",
                "browser_started":False, "published":False}
    # Account selectors are explicit, never guessed from the last used session.
    if service == "youtube" and brand != "nkw":
        return {"status":"choose_target_brand", "valid_brands":["nkw"],
                "browser_started":False, "published":False}
    if service == "google_search_console" and brand not in {"anita", "weterynarz"}:
        return {"status":"choose_target_brand", "valid_brands":["anita", "weterynarz"],
                "browser_started":False, "published":False}
    if service in {"github", "render"} and brand != "aibrowser":
        return {"status":"choose_target_brand", "valid_brands":["aibrowser"],
                "browser_started":False, "published":False}
    if service == "google_drive" and brand:
        return {"status":"choose_target_brand", "valid_brands":[""],
                "browser_started":False, "published":False}
    if service not in {"youtube", "google_search_console", "github", "render", "google_drive"} and brand in {"nkw", "aibrowser"}:
        return {"status":"unsupported_request", "browser_started":False, "published":False}
    if service in {"instagram","facebook","wordpress","google_business"} and not brand:
        return {"status":"choose_target_brand",
                "browser_started":False,"published":False,
                "valid_brands":["anita","weterynarz"]}

    requested_operation = operation
    operation = READ_ALIASES.get((service, operation), operation)
    target=BRAND_TARGET.get(brand, {})
    result={
        "router_version":ROUTER_VERSION,
        "service":service,
        "operation":operation,
        "requested_operation":requested_operation,
        "brand":brand or "account_check_required",
        "status":"available_route_hint_only",
        "connector_connected":"not_checked",
        "account_authenticated":"not_checked",
        "account_match":"not_checked",
        "browser_started":False,
        "published":False,
        "requires_live_connector_probe":True,
        "requires_exact_account_match":True,
        "requires_concrete_content_for_write":operation in WRITES,
        "can_silently_retry_login":False,
        "captcha_handling":"bounded_provider_solver_when_enabled_then_scoped_owner_fallback",
        "privacy":"never_request_password_or_otp_in_chat",
        "access_recovery":{key: plan_access_recovery(key) for key in ACCESS_RECOVERY},
    }

    if service=="instagram":
        result["expected_account_id"]=target["instagram"]
        result["browser_profile_if_required"]=target["browser_meta"]
    elif service=="facebook":
        result["expected_account_id"]=target["facebook"]
        result["browser_profile_if_required"]=target["browser_meta"]
    elif service=="google_business":
        result["expected_account_id"]=target["google_business"]
        result["browser_profile_if_required"]=target["browser_google"]
    elif service=="wordpress":
        result["expected_site_url"]=target["wordpress"]
        # A Google profile is not automatically a WordPress login.
        result["browser_profile_if_required"]="explicit_verified_wordpress_profile"
    elif service=="youtube":
        result["expected_account_id"]="UC7EQ32QjfKQ7bFiVdGAhB-A"
        result["browser_profile_if_required"]="NKW - YouTube Studio"
        result["browser_fallback_requires_live_identity_check"]=True
        result["browser_fallback_does_not_bypass_google_login_policy"]=True
    elif service=="google_search_console":
        result["expected_site_url"]=(
            "https://architekt.radom.pl" if brand=="anita"
            else "https://weterynarz.radom.pl"
        )
        result["requires_verified_property_binding"]=True
    elif service=="github":
        result["expected_repo"]="napieraj2018-arch/Watcher-15"
        result["browser_fallback_permitted"]=False
    elif service=="render":
        result["expected_service_id"]="srv-db34e6ks728c73bae4sg"
        result["expected_workspace_id"]="tea-db33rcjncjis73ecbbj0"
        result["browser_fallback_permitted"]=False
    elif service=="google_drive":
        result["requires_verified_drive_scope"]=True
        result["browser_fallback_permitted"]=False
    elif service=="browser":
        result["status"]="browser_state_verification_required"
        result["browser_profile_if_required"]="explicit_owner_selected_profile"
        result["requires_live_connector_probe"]=False
        return result

    if service=="gmail" and operation not in {"email_read","email_draft","email_send","email_verify"}:
        result["status"]="unsupported_action"
        result["reason"]="select_a_known_gmail_operation"
        return result
    if brand=="weterynarz" and service in {"instagram","facebook","google_business"}:
        # The profile is not necessarily connected to Windsor/Meta.
        result["status"]="connector_scope_needs_verification"
        result["reason"]="exact_vet_social_account_not_verified"
        return result
    if (service,operation) in NO_VERIFIED_API:
        result["status"]="browser_fallback_may_be_required"
        result["reason"]="no_verified_connector_action_for_exact_media_type"
        result["next_step"]="check_authorized_browser_profile_then_live_auth_identity"
        return result
    route=API_ROUTE.get((service,operation))
    if route is None:
        result["status"]="unsupported_action"
        result["reason"]="do_not_guess_connector_action"
        return result
    app,connector,action,requirements=route
    result["preferred_path"]="connected_chatgpt_application"
    result["plugin"]=app
    result["connector"]=connector
    result["action"]=action
    result["required_inputs"]=list(requirements)
    result["next_step"]="probe_connector_account_and_action_permissions"
    if service == "gmail" and operation == "email_verify":
        result["verification_plan"] = email_confirmation_plan()
        result["next_step"] = "bind_current_confirmation_flow_to_exact_connected_mailbox"
    if service in {"instagram", "facebook", "google_business"} and operation == "read":
        # Provider-supported business fields, not private groups or Highlights.
        result["read_scope"] = "business_account_supported_fields_only"
    if operation in WRITES:
        result["must_verify_target_and_payload_before_write"]=True
        result["do_not_retry_write_without_idempotency_readback"]=True
    return deepcopy(result)
