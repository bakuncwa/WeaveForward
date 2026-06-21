import logging
import resend
from django.conf import settings
from django.utils.html import escape


logger = logging.getLogger(__name__)

def send_password_reset_email(to_email, reset_link):
    resend.api_key = settings.RESEND_API_KEY
    
    params = {
        "from": "WeaveForward <no-reply@weaveforward.online>",
        "to": [to_email],
        "subject": "Reset Your WeaveForward Password",
        "html": f"""
            <div style="font-family: sans-serif; max-width: 600px; margin: auto; padding: 20px; border: 1px solid #eee; border-radius: 10px;">
                <h2 style="color: #2D3748;">Password Reset Request</h2>
                <p>Hello,</p>
                <p>We received a request to reset your password for your WeaveForward account. Click the button below to proceed:</p>
                <div style="text-align: center; margin: 30px 0;">
                    <a href="{reset_link}" style="background-color: #4A5568; color: white; padding: 12px 24px; text-decoration: none; border-radius: 5px; font-weight: bold;">Reset Password</a>
                </div>
                <p>If you didn't request this, you can safely ignore this email.</p>
                <p>Best regards,<br>The WeaveForward Team</p>
                <hr style="border: 0; border-top: 1px solid #eee; margin: 20px 0;">
                <p style="font-size: 12px; color: #A0AEC0;">If the button above doesn't work, copy and paste this link into your browser:</p>
                <p style="font-size: 12px; color: #A0AEC0;">{reset_link}</p>
            </div>
        """,
    }

    try:
        email = resend.Emails.send(params)
        return email
    except Exception as e:
        return None


def send_verification_email(to_email, verify_link, display_name):
    resend.api_key = settings.RESEND_API_KEY
    safe_display_name = escape(display_name)
    safe_verify_link = escape(verify_link)

    params = {
        "from": "WeaveForward <no-reply@weaveforward.online>",
        "to": [to_email],
        "subject": "Verify Your WeaveForward Account",
        "html": f"""
            <div style="font-family: sans-serif; max-width: 600px; margin: auto; padding: 20px; border: 1px solid #eee; border-radius: 10px;">
                <h2 style="color: #2D3748;">Welcome to WeaveForward!</h2>
                <p>Hello {safe_display_name},</p>
                <p>Please verify your email address by clicking the button below:</p>
                <div style="text-align: center; margin: 30px 0;">
                    <a href="{safe_verify_link}" style="background-color: #4A5568; color: white; padding: 12px 24px; text-decoration: none; border-radius: 5px; font-weight: bold;">Verify Email</a>
                </div>
                <p>This link stays valid until your account is verified. If you didn't create an account, you can ignore this email.</p>
                <p>Best regards,<br>The WeaveForward Team</p>
                <hr style="border: 0; border-top: 1px solid #eee; margin: 20px 0;">
                <p style="font-size: 12px; color: #A0AEC0;">If the button doesn't work, copy and paste this link:</p>
                <p style="font-size: 12px; color: #A0AEC0;">{safe_verify_link}</p>
            </div>
        """,
    }

    try:
        return resend.Emails.send(params)
    except Exception as e:
        logger.error("Failed to send verification email to %s: %s", to_email, e)
        return None


def send_match_accept_notification(donor_email, donor_name, tuab_name,
                                    pickup_address, pickup_date, items_list):
    resend.api_key = settings.RESEND_API_KEY

    items_html = "".join(
        f"<li><strong>{i['brand']}</strong> &mdash; {i['clothing_type']} "
        f"({i['condition']}, {i['weight']} kg)"
        f"</li>"
        for i in items_list
    )

    params = {
        "from": "WeaveForward <no-reply@weaveforward.online>",
        "to": [donor_email],
        "subject": f"{tuab_name} is Interested in Your Donation Items",
        "html": f"""
            <div style="font-family: sans-serif; max-width: 600px; margin: auto; padding: 20px; border: 1px solid #eee; border-radius: 10px;">
                <h2 style="color: #2D3748;">A TUAB is Interested in Your Items!</h2>
                <p>Hello {donor_name},</p>
                <p>Great news! <strong>{tuab_name}</strong> has shown interest in some items from your donation.</p>
                <h3>Interested Items:</h3>
                <ul>{items_html}</ul>
                <h3>Pickup Location:</h3>
                <p>{pickup_address}</p>
                <p>Preferred Pickup Date: {pickup_date}</p>
                <p>Log in to your account to view your donation details and track its status.</p>
                <p>Best regards,<br>The WeaveForward Team</p>
            </div>
        """,
    }

    try:
        return resend.Emails.send(params)
    except Exception as e:
        logger.error("Failed to send accept notification to %s: %s", donor_email, e)
        return None


def send_match_reject_notification(donor_email, donor_name, tuab_name,
                                    items_list):
    resend.api_key = settings.RESEND_API_KEY

    items_html = "".join(
        f"<li><strong>{i['brand']}</strong> &mdash; {i['clothing_type']} "
        f"({i['condition']}, {i['weight']} kg)"
        f"</li>"
        for i in items_list
    )

    params = {
        "from": "WeaveForward <no-reply@weaveforward.online>",
        "to": [donor_email],
        "subject": f"{tuab_name} Has Reviewed Your Donation Items",
        "html": f"""
            <div style="font-family: sans-serif; max-width: 600px; margin: auto; padding: 20px; border: 1px solid #eee; border-radius: 10px;">
                <h2 style="color: #2D3748;">TUAB Review Update</h2>
                <p>Hello {donor_name},</p>
                <p><strong>{tuab_name}</strong> has reviewed some items from your donation. Some items were not a fit for their current materials needs.</p>
                <h3>Items Reviewed:</h3>
                <ul>{items_html}</ul>
                <p>Don't worry — your donation is still listed and other TUABs may be interested.</p>
                <p>Log in to your account to review your donation and explore other options.</p>
                <p>Best regards,<br>The WeaveForward Team</p>
            </div>
        """,
    }

    try:
        return resend.Emails.send(params)
    except Exception as e:
        logger.error("Failed to send reject notification to %s: %s", donor_email, e)
        return None


def send_flag_notification(admin_emails, donation_id, flag_reason, flagged_by_name, donor_name, pickup_city):
    resend.api_key = settings.RESEND_API_KEY

    if len(flag_reason) > 500:
        flag_reason = flag_reason[:500] + "..."
    flag_reason = escape(flag_reason)

    params = {
        "from": "WeaveForward <no-reply@weaveforward.online>",
        "to": admin_emails,
        "subject": f"Donation #{donation_id} Flagged for Review",
        "html": f"""
            <div style="font-family: sans-serif; max-width: 600px; margin: auto; padding: 20px; border: 1px solid #eee; border-radius: 10px;">
                <h2 style="color: #2D3748;">Donation Flagged for Review</h2>
                <p>A donation has been flagged and requires admin review.</p>
                <table style="width:100%; border-collapse: collapse; margin: 16px 0;">
                    <tr><td style="padding:8px; border-bottom:1px solid #eee; color:#718096;">Donation ID</td><td style="padding:8px; border-bottom:1px solid #eee; font-weight:bold;">#{donation_id}</td></tr>
                    <tr><td style="padding:8px; border-bottom:1px solid #eee; color:#718096;">Flagged By</td><td style="padding:8px; border-bottom:1px solid #eee;">{flagged_by_name}</td></tr>
                    <tr><td style="padding:8px; border-bottom:1px solid #eee; color:#718096;">Donor</td><td style="padding:8px; border-bottom:1px solid #eee;">{donor_name}</td></tr>
                    <tr><td style="padding:8px; border-bottom:1px solid #eee; color:#718096;">Pickup City</td><td style="padding:8px; border-bottom:1px solid #eee;">{pickup_city}</td></tr>
                    <tr><td style="padding:8px; border-bottom:1px solid #eee; color:#718096;">Reason</td><td style="padding:8px; border-bottom:1px solid #eee;">{flag_reason}</td></tr>
                </table>
                <p>Log in to the admin panel to review and take action on this flag.</p>
                <p>Best regards,<br>The WeaveForward Team</p>
            </div>
        """,
    }

    try:
        return resend.Emails.send(params)
    except Exception as e:
        logger.error("Failed to send flag notification for donation #%s: %s", donation_id, e)
        return None
