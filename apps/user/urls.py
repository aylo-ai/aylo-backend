from django.urls import path

import user.views as views

app_name = "user"

urlpatterns = [
    path("auth/send-otp/", views.SendCodeView.as_view()),
    path("auth/verify-otp/", views.VerifyCodeView.as_view()),
    path("auth/register/", views.UserRegisterView.as_view()),
    path("auth/login/refresh/", views.LoginRefreshView.as_view()),
    path("auth/profile/", views.UserProfileGetView.as_view()),
    path("auth/update-user/", views.UpdateProfileView.as_view()),
    path("auth/logout/", views.LogoutView.as_view()),

    path("privacy-policy/", views.PrivacyPolicyListCreateView.as_view()),
    path("privacy-policy/<uuid:pk>/", views.PrivacyPolicyRetrieveView.as_view()),
    path("user-agreement/", views.UserAgreementListCreateView.as_view()),
    path("user-agreement/<uuid:pk>/", views.UserAgreementRetrieveView.as_view()),
]