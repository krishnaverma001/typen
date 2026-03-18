# writing/views

from django.contrib.auth import login, logout, authenticate
from django.shortcuts import render, redirect
from .forms import UserRegisterForm, UserLoginForm

def signup_view(request):
    if request.method == 'POST':
        form = UserRegisterForm(request.POST)
        if form.is_valid():
            user = form.save(commit=False)
            user.set_password(form.cleaned_data['password'])  # hash password
            user.save()
            login(request, user)
            return redirect('home')
    else:
        form = UserRegisterForm()
    return render(request, 'user/signup.html', {'form': form})

def login_view(request):
    if request.method == 'POST':
        form = UserLoginForm(request, data=request.POST)
        if form.is_valid():
            user = form.get_user()
            login(request, user)
            return redirect('/')
    else:
        form = UserLoginForm()

    return render(request, 'user/login.html', {'form': form})

def logout_view(request):
    logout(request)
    return redirect('login')