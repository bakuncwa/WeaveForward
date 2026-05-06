import os
from django.core.management.base import BaseCommand
from backend.models import User, UserAccountStatus, UserRole

class Command(BaseCommand):
    help = 'Create or update admin user from environment variables'

    def handle(self, *args, **options):
        email = os.getenv('ADMIN_EMAIL')
        password = os.getenv('ADMIN_PASSWORD')
        
        # Note: We use email as the username in this project
        if not email or not password:
            self.stdout.write(self.style.WARNING('ADMIN_EMAIL or ADMIN_PASSWORD not set. Skipping admin setup.'))
            return

        user, created = User.objects.get_or_create(
            email=email,
            defaults={
                'role': UserRole.ADMIN,
                'status': UserAccountStatus.ACTIVE,
                'contact_no': '00000000000' # Required field
            }
        )

        user.set_password(password)
        user.save()

        if created:
            self.stdout.write(self.style.SUCCESS(f'Admin user created: {email}'))
        else:
            self.stdout.write(self.style.SUCCESS(f'Admin user password updated: {email}'))
