"""Safe routing hints: use a connected ChatGPT app before Steel browser login.

This is a READ-ONLY declarative planner. It has NO access to ChatGPT plugins,
OAuth tokens, Steel cookies, private task history or customer accounts.
The ChatGPT agent MUST recheck the actual connector, account identity,
action schema and content material before taking any action. A route hint
never authorizes publication, confirms authentication or submits a form.
"""
from __future__ import annotations

from copy import deepcopy

ROUTER_VERSION = "2026-10-10.1"
BRANDS = frozenset(("", "anita", "weterynarz"))
SERVICES = frozenset((
    "instagram", "facebook", "gmail", "wordpress", "google_business",
    "windsor", "metricool", "browser",
))
OPERATIONS = frozenset((
    "read", "post", "image_post", "reel", "story", "carousel",
    "highlights", "reviews", "email_read", "email_draft", "email_send",
    "wordpress_read", "wordpress_draft", "wordpress_publish",
    "business_reviews", "business_post", "analytics",
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

# Operations that really exist on the currently connected ChatGPT plugins.
# DO NOT imply that a given profile is authenticated until fresh readback.
API_ROUTE = {
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
))


def plan_operation(service: str, operation: str, brand: str = "") -> dict:
    """Return safe, public, non-authoritative route information.

    Unknown requests and ambiguous account choices fail closed.
    This tool NEVER publishes and does not accept content, URLs or secrets.
    """
    if (type(service) is not str or type(operation) is not str
        or type(brand) is not str or service not in SERVICES
        or operation not in OPERATIONS or brand not in BRANDS):
        return {"status":"unsupported_request",
                "browser_started":False, "published":False}
    if service in {"instagram","facebook","wordpress","google_business"} and not brand:
        return {"status":"choose_target_brand",
                "browser_started":False,"published":False,
                "valid_brands":["anita","weterynarz"]}

    target=BRAND_TARGET.get(brand, {})
    result={
        "router_version":ROUTER_VERSION,
        "service":service,
        "operation":operation,
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
        "captcha_handling":"human_verification_required_if_present",
        "privacy":"never_request_password_or_otp_in_chat",
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
        result["browser_profile_if_required"]=target["browser_google"]
    elif service=="browser":
        result["status"]="browser_authentication_required"
        result["browser_profile_if_required"]="explicit_owner_selected_profile"
        result["requires_live_connector_probe"]=False
        return result

    if service=="gmail" and operation not in {"email_read","email_draft","email_send"}:
        result["status"]="unsupported_action"
        result["reason"]="select_a_known_gmail_operation"
        return result
    if brand=="weterynarz" and service in {"instagram","facebook","google_business"}:
        # The profile is not necessarily connected to Windsor/Meta;
        # the user must explicitly choose the legal brand account.
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
    if operation in WRITES:
        result["must_verify_target_and_payload_before_write"]=True
        result["do_not_retry_write_without_idempotency_readback"]=True
    return deepcopy(result)
