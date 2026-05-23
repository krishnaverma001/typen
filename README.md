---
title: Typen
emoji: ✍️
colorFrom: blue
colorTo: purple
sdk: docker
pinned: false
---

# Typen - Handwriting Generation Platform

Transform text into beautifully handwritten documents using transformers.

Inspiration from Alex Geeves paper: https://arxiv.org/abs/1308.0850

## Features

- Realistic handwriting generation - Neural network generates natural looking handwritten text

- Multiple handwriting styles - Choose from 13 different pre-trained writing styles

- Adjustable writing variation - Control randomness and neatness with bias parameter

- Customizable appearance - Adjust stroke width, ink color, and margin/padding layouts

- A4 page formatting - Automatic pagination with proper page numbering

- User accounts - Save and manage your generated documents in sessions

- Generation history - Browse and revisit your past handwriting samples

- Export options (upcoming) - Download individual pages as responsive SVG files

## Setup

```
# Clone the repository
git clone https://github.com/krishnaverma001/typen.git

cd typen

# Create conda environment with Python 3.6 (TensorFlow 1.x compatible)
conda create -n typen python=3.6 -y
conda activate typen

# Install dependencies
pip install -r requirements.txt

# Set up environment variables
mv .env.example .env

# Edit .env with your Django secret key and superuser credentials

# Run migrations
python manage.py makemigrations
python manage.py migrate

# Start the development server
python manage.py runserver
```

## Structure

```
typen/
├── user/                   # User authentication app
│   ├── models.py           # CustomUser model with profile images
│   ├── forms.py            # Registration and login forms
│   ├── views.py            # Auth views
│   └── signals.py          # Auto-create superuser from env (admin access for deployment)
│
├── writing/                # Main handwriting generation app
│   ├── models.py           # Generation, UserImage, UsageStats
│   ├── views.py            # Generate, history, detail endpoints
│   ├── urls.py             # API routes
│   └── ml/                 # Handwriting generation engine
│       │
│       ├── generator.py    # HandwritingGenerator class
│       ├── rnn.py          # RNN model with attention
│       ├── rnn_cell.py     # LSTM attention cell
│       ├── drawing.py      # Stroke processing utilities
│       ├── checkpoints/    # Pre-trained model weights
│       └── styles/         # Style stroke data (style-*.npy)
│
├── config/                 # Django project settings
│   ├── settings.py         # Main settings (Sqlite by default, PostgreSQL ready)
│   └── urls.py             # Main URL routing
│
├── media/                  # User-generated SVG files (per session)  (Local)
├── static/                 # Static files (CSS, JS)                  (Production)
├── templates/              # Frontend templates
├── logs/                   # Application logs
└── requirements.txt
```
## Demo

![Demo](demo.png)

## Deployment  [![Live Demo](https://img.shields.io/badge/Live%20Demo-🔗-blue)](https://krishnaverma01-typen.hf.space)

https://krishnaverma01-typen.hf.space

## Contributing

Contributions are welcome! Areas for improvement:

- Upgrade to TensorFlow 2.x
- Add PDF export support
- Add more handwriting styles
- Implement concurrency and multi-threading

##  Acknowledgments
- Based on Sean Vasquez's handwriting-synthesis implementation
- Pretrained model from the original paper's experiments
- IAM On-Line Handwriting Database for training data