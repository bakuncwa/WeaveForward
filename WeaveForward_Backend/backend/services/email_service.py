import resend
from django.conf import settings

def send_password_reset_email(to_email, reset_link):
    resend.api_key = settings.RESEND_API_KEY
    
    params = {
        "from": "WeaveForward <onboarding@resend.dev>", # Default for free tier
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
        print(f"Error sending email: {e}")
        return None
