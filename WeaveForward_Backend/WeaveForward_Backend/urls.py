import os
from django.contrib import admin
from django.contrib.auth import authenticate, login
from django.contrib.auth.forms import AuthenticationForm
from django.http import HttpResponseRedirect
from django.shortcuts import render
from django.urls import path, include, re_path
from django.conf import settings
from django.views.static import serve
from django.contrib import messages


def admin_login(request):
    form = AuthenticationForm(request, data=request.POST or None)
    if request.method == 'POST':
        user = authenticate(request, email=request.POST.get('username'), password=request.POST.get('password'))
        if user is not None:
            if user.email != os.environ.get('ADMIN_EMAIL', ''):
                messages.error(request, 'Access denied.')
                return render(request, 'admin/login.html', {'form': form, 'site_header': admin.site.site_header})
            login(request, user)
            return HttpResponseRedirect('/admin/')
        messages.error(request, 'Invalid email or password.')
    return render(request, 'admin/login.html', {'form': form, 'site_header': admin.site.site_header})


urlpatterns = [
    path('admin/login/', admin_login, name='admin_login'),
    path('admin/', admin.site.urls),
    path('api/', include('backend.urls')),
]

if not settings.USE_GCS:
    urlpatterns.append(
        re_path(r'^media/(?P<path>.*)$', serve, {'document_root': settings.MEDIA_ROOT})
    )
