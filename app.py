import os
from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify
from flask_bcrypt import Bcrypt
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from flask_mail import Mail, Message
from dotenv import load_dotenv
from functools import wraps
import boto3
import io
from botocore.client import Config
from werkzeug.utils import secure_filename
from sqlalchemy import or_ # We'll need this for the search API later
from models import Annotation, AnnotationLayer, StudyGroup, User, Ebook, Category, SupportMessage, BookSubmission # Add these to your imports at the top
from models import db, bcrypt  # <-- ADD THIS LINE
import ai_tools
import requests

# --- Configuration ---
load_dotenv()

app = Flask(__name__)

# Load all configurations from .env
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY')
app.config['ADMIN_SECRET_CODE'] = os.getenv('ADMIN_SECRET_CODE') # For admin registration
app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv('DATABASE_URI')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SQLALCHEMY_POOL_PRE_PING'] = True
app.config['SQLALCHEMY_POOL_RECYCLE'] = 280

# Email Configuration (for contact form)
app.config['MAIL_SERVER'] = os.getenv('MAIL_SERVER')
app.config['MAIL_PORT'] = int(os.getenv('MAIL_PORT', 587))
app.config['MAIL_USE_TLS'] = os.getenv('MAIL_USE_TLS', 'True').lower() in ['true', '1', 't']
app.config['MAIL_USERNAME'] = os.getenv('MAIL_USERNAME')
app.config['MAIL_PASSWORD'] = os.getenv('MAIL_PASSWORD')

# AWS S3 Configuration (for file uploads)
AWS_ACCESS_KEY_ID = os.getenv('AWS_ACCESS_KEY_ID')
AWS_SECRET_ACCESS_KEY = os.getenv('AWS_SECRET_ACCESS_KEY')
AWS_BUCKET_NAME = os.getenv('AWS_BUCKET_NAME')
AWS_REGION = os.getenv('AWS_REGION')

# --- Initialize Extensions ---
db.init_app(app)
bcrypt.init_app(app)
mail = Mail(app)
migrate = Migrate(app, db)
# Note: We will initialize the s3_client later inside the relevant routes

# --- S3 Client Initialization ---
AWS_ACCESS_KEY_ID = os.getenv('AWS_ACCESS_KEY_ID')
AWS_SECRET_ACCESS_KEY = os.getenv('AWS_SECRET_ACCESS_KEY')
AWS_BUCKET_NAME = os.getenv('AWS_BUCKET_NAME')
AWS_REGION = os.getenv('AWS_REGION')
S3_ENDPOINT_URL = os.getenv('S3_ENDPOINT_URL') # <-- This line is new

s3_client = None
try:
    # Check for the minimal config
    if AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY and AWS_BUCKET_NAME:
        
        if S3_ENDPOINT_URL:
            # We are using an S3-compatible alternative (like Backblaze B2)
            s3_client = boto3.client(
                "s3",
                endpoint_url=S3_ENDPOINT_URL,
                aws_access_key_id=AWS_ACCESS_KEY_ID,
                aws_secret_access_key=AWS_SECRET_ACCESS_KEY,
                region_name=AWS_REGION
            )
            print(f"[*] S3-compatible client configured for endpoint: {S3_ENDPOINT_URL}")
        
        elif AWS_REGION:
            # We are using the default AWS S3

            # This is the new, simpler config.
            # We only specify the signature, not the region.
            s3_config = Config(
                signature_version = 's3v4',
            )

            s3_client = boto3.client(
               "s3",
               aws_access_key_id=AWS_ACCESS_KEY_ID,
               aws_secret_access_key=AWS_SECRET_ACCESS_KEY,
               region_name=AWS_REGION, # The client needs the region
               config=s3_config          # Pass in the simple config
            )
            print("[*] AWS S3 client configured successfully (with s3v4 signature).")
        
        else:
            print("[!] Warning: S3 config missing AWS_REGION (for AWS) or S3_ENDPOINT_URL (for alternatives).")

    else:
        print("[!] Warning: Missing S3 credentials or config.")
except Exception as e:
    print(f"[!] Warning: Could not configure S3 client. Error: {e}")

# --- Decorators (Access Control) ---
# Reused from your project

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'logged_in' not in session:
            flash('Please log in to access this page.', 'info')
            return redirect(url_for('auth'))
        return f(*args, **kwargs)
    return decorated_function

def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'is_admin' not in session or not session['is_admin']:
            flash('You do not have permission to access this page.', 'danger')
            return redirect(url_for('dashboard')) # Redirect non-admins to main dashboard
        return f(*args, **kwargs)
    return decorated_function

# --- Authentication Routes (Reused from your project) ---
# We adapted this to use our new single 'User' model

@app.route('/auth', methods=['GET', 'POST'])
def auth():
    if request.method == 'POST':
        if 'register' in request.form:
            # --- Registration Logic ---
            is_admin_request = 'admin_toggle' in request.form
            admin_code = request.form.get('admin_code', '')
            
            email = request.form['email']
            username = request.form['username']
            password = request.form['password']
            
            # Check for existing user
            existing_user = User.query.filter(
                (User.username == username) | (User.email == email)
            ).first()
            
            if existing_user:
                flash('Username or email already exists.', 'danger')
                return redirect(url_for('auth'))
            
            is_admin = False
            if is_admin_request:
                if admin_code == app.config['ADMIN_SECRET_CODE']:
                    is_admin = True
                else:
                    flash('Invalid Admin Code. Registration as admin failed.', 'danger')
                    return redirect(url_for('auth'))

            # Create new user
            new_user = User(
                email=email,
                username=username,
                first_name=request.form['first_name'],
                last_name=request.form['last_name'],
                is_admin=is_admin
            )
            new_user.set_password(password) # Hash the password
            
            db.session.add(new_user)
            db.session.commit()
            
            flash('Successfully registered! Please log in.', 'success')
            return redirect(url_for('auth'))
        
        elif 'login' in request.form:
            # --- Login Logic ---
            username = request.form['username']
            password_candidate = request.form['password']
            
            user = User.query.filter_by(username=username).first()
            
            if user and user.check_password(password_candidate):
                # Password is correct, create session
                session['logged_in'] = True
                session['user_id'] = user.id
                session['username'] = user.username
                session['is_admin'] = user.is_admin
                
                if user.is_admin:
                    return redirect(url_for('admin_dashboard'))
                else:
                    return redirect(url_for('dashboard'))
            else:
                flash('Invalid username or password.', 'danger')
                return redirect(url_for('auth'))

    # GET request just shows the auth page
    return render_template('auth.html')

@app.route('/logout')
@login_required
def logout():
    session.clear()
    flash('You have been logged out.', 'success')
    return redirect(url_for('auth'))

# --- Admin Routes (Placeholder) ---
# --- Admin (Librarian) Routes ---
# We are porting these from your original project and adapting them.

@app.route('/admin/dashboard')
@admin_required
def admin_dashboard():
    """
    Shows the main admin dashboard.
    Displays all books, categories, and pending submissions.
    """
    try:
        ebooks = Ebook.query.order_by(Ebook.title).all()
        categories = Category.query.order_by(Category.name).all()
        # Fetch pending submissions
        submissions = BookSubmission.query.filter_by(status='pending').order_by(BookSubmission.timestamp.desc()).all()
    except Exception as e:
        flash(f'Error fetching dashboard data: {e}', 'danger')
        ebooks = []
        categories = []
        submissions = []
        
    return render_template(
        'admin/dashboard.html', 
        ebooks=ebooks, 
        categories=categories,
        submissions=submissions # Pass submissions to the template
    )

@app.route('/admin/upload', methods=['GET', 'POST'])
@admin_required
def admin_upload():
    """
    Handles the upload of a new book by an admin.
    Uploads the file directly to S3 and creates a new Ebook record.
    """
    if not s3_client:
        flash('Cloud storage (S3) is not configured. Cannot upload files.', 'danger')
        return redirect(url_for('admin_dashboard'))

    if request.method == 'POST':
        title = request.form['title']
        author_name = request.form['author_name']
        category_id = request.form.get('category_id')
        manual_cover_url = request.form.get('cover_image_url') # <--- Get the manual input
        ebook_file = request.files.get('ebook_file') 

        if not all([title, author_name, category_id, ebook_file]):
            flash('All fields and a file are required.', 'danger')
            return redirect(url_for('admin_upload'))

        if ebook_file and ebook_file.filename.lower().endswith('.pdf'):
            # Create a secure filename for the S3 key
            filename = secure_filename(ebook_file.filename) 

            try:
                # Upload the file stream directly to S3
                s3_client.upload_fileobj(
                    ebook_file,              # The file stream
                    AWS_BUCKET_NAME,         # Bucket name
                    filename,                # S3 Key (filename)
                    ExtraArgs={'ContentType': 'application/pdf'}
                )

                # 1. Extract text
                print(f"[*] Extracting text for AI memory...")
                extracted_text = ai_tools.extract_text_from_pdf_strategically(
                    s3_client, 
                    AWS_BUCKET_NAME, 
                    filename 
                )
                
                # --- NEW LOGIC: Check Manual URL vs Auto-Fetch ---
                if manual_cover_url and manual_cover_url.strip():
                    print(f"[*] Using manual cover URL provided by admin...")
                    cover_url = manual_cover_url.strip()
                else:
                    print(f"[*] Fetching book cover from Google...")
                    cover_url = ai_tools.fetch_book_cover(title, author_name)
                # -------------------------------------------------

                # 2. Save ebook details
                new_ebook = Ebook(
                    title=title,
                    author_name=author_name,
                    file_path=filename, 
                    category_id=category_id,
                    submitted_by_id=session['user_id'],
                    text_content=extracted_text,
                    cover_image_url=cover_url # <--- Save whichever URL we got
                )
                db.session.add(new_ebook)
                db.session.commit() 

                # --- AI FEATURE INTEGRATION ---
                try:
                    print(f"[*] Calling AI to generate starter layers for: {new_ebook.title}")
                    layer_data = ai_tools.generate_starter_layers(
                        new_ebook, 
                        s3_client, 
                        AWS_BUCKET_NAME
                    )
                    
                    if layer_data.get('success'):
                        for layer_name in layer_data.get('layers', []):
                            new_layer = AnnotationLayer(
                                name=layer_name,
                                description="Auto-generated by AI",
                                is_public=True,
                                creator_id=session['user_id'],
                                ebook_id=new_ebook.id
                            )
                            db.session.add(new_layer)
                        db.session.commit()
                        print(f"[*] AI successfully generated {len(layer_data.get('layers', []))} layers.")
                        flash(f'"{title}" uploaded and AI generated {len(layer_data.get("layers", []))} starter layers.', 'success')
                    else:
                        print(f"[!] AI layer generation failed: {layer_data.get('error')}")
                        flash(f'"{title}" uploaded, but AI layer generation failed. {layer_data.get("error")}', 'warning')

                except Exception as ai_e:
                    print(f"[!] Critical error during AI layer generation: {ai_e}")
                    flash(f'"{title}" uploaded, but a critical error occurred during AI processing.', 'danger')
                
                return redirect(url_for('admin_dashboard'))

            except Exception as e:
                db.session.rollback()
                print(f"[!] Error uploading to S3 or saving to DB: {e}")
                flash(f'Error during upload: {e}', 'danger')
                return redirect(url_for('admin_upload'))
        else:
            flash('Invalid or missing file. Only PDF files are allowed.', 'danger')

    # GET request: Show the upload form
    categories = Category.query.order_by(Category.name).all()
    return render_template('admin/upload_book.html', categories=categories)

@app.route('/admin/edit-ebook/<int:ebook_id>', methods=['GET', 'POST'])
@admin_required
def edit_ebook(ebook_id):
    """
    Edit an existing ebook's metadata.
    Does not handle file re-uploads.
    """
    ebook_to_edit = db.session.get(Ebook, ebook_id)
    if not ebook_to_edit:
        flash('Ebook not found.', 'danger')
        return redirect(url_for('admin_dashboard'))

    if request.method == 'POST':
        try:
            ebook_to_edit.title = request.form['title']
            ebook_to_edit.author_name = request.form['author_name']
            ebook_to_edit.category_id = request.form.get('category_id')
            db.session.commit()
            flash(f'"{ebook_to_edit.title}" has been updated.', 'success')
            return redirect(url_for('admin_dashboard'))
        except Exception as e:
            db.session.rollback()
            flash(f'Error updating book: {e}', 'danger')

    # GET request: Show the edit form
    categories = Category.query.order_by(Category.name).all()
    return render_template('admin/edit_book.html', ebook=ebook_to_edit, categories=categories)

@app.route('/admin/delete-ebook/<int:ebook_id>', methods=['POST'])
@admin_required
def delete_ebook(ebook_id):
    """
    Deletes an ebook from the database AND from the S3 bucket.
    """
    ebook_to_delete = db.session.get(Ebook, ebook_id)
    if not ebook_to_delete:
        flash('Ebook not found.', 'danger')
        return redirect(url_for('admin_dashboard'))

    try:
        # Step 1: Delete the file from S3
        if s3_client and ebook_to_delete.file_path:
            s3_client.delete_object(
                Bucket=AWS_BUCKET_NAME, 
                Key=ebook_to_delete.file_path
            )
        
        # Step 2: Delete the book record from the database
        # All related annotations/layers will be cascade deleted
        db.session.delete(ebook_to_delete)
        db.session.commit()
        
        flash(f'"{ebook_to_delete.title}" and its file have been deleted.', 'success')
    except Exception as e:
        db.session.rollback()
        print(f"[!] Error deleting ebook {ebook_id}: {e}")
        flash(f'Error deleting book: {e}', 'danger')
        
    return redirect(url_for('admin_dashboard'))


@app.route('/admin/submissions')
@admin_required
def submission_queue():
    """
    Admin page to view all pending book submissions.
    """
    try:
        submissions = BookSubmission.query.filter_by(status='pending').order_by(BookSubmission.timestamp.desc()).all()
        categories = Category.query.order_by(Category.name).all() # <-- We need this for the modal
    except Exception as e:
        flash(f'Error fetching submissions: {e}', 'danger')
        submissions = []
        categories = []
        
    return render_template(
        'admin/submission_queue.html', 
        submissions=submissions,
        categories=categories # <-- Pass categories to the template
    )

@app.route('/api/ai/explain', methods=['POST'])
@login_required
def explain_text():
    """
    API: Answers a user's question based on the book's content.
    """
    data = request.json
    user_question = data.get('text') 
    ebook_id = data.get('ebook_id')
    
    if not user_question:
        return jsonify({'error': 'Please ask a question.'}), 400
        
    # Fetch book details AND the saved text
    ebook = db.session.get(Ebook, ebook_id)
    if not ebook:
        return jsonify({'error': 'Book not found'}), 404

    title = ebook.title
    author = ebook.author_name
    # Get the text we saved during upload. If missing, use a placeholder.
    book_context = ebook.text_content if ebook.text_content else "Text not available."

    # Call the AI
    response = ai_tools.analyze_user_note(user_question, title, author, book_context)
    
    return jsonify({'explanation': response})

@app.route('/admin/approve-submission/<int:sub_id>', methods=['POST'])
@admin_required
def approve_submission(sub_id):
    submission = db.session.get(BookSubmission, sub_id)
    category_id = request.form.get('category_id')

    if not submission:
        flash('Submission not found.', 'danger')
        return redirect(url_for('submission_queue'))
        
    if not category_id:
        flash('You must select a category to approve a book.', 'danger')
        return redirect(url_for('submission_queue'))

    if not submission.pending_file_path:
        flash('This submission has no file associated with it. Cannot approve.', 'danger')
        return redirect(url_for('submission_queue'))

    try:
        # 1. Define new S3 key (moving it out of 'pending-uploads/')
        new_s3_key = submission.pending_file_path.split('/')[-1]
        
        # 2. Copy the object in S3 to the new location
        s3_client.copy_object(
            Bucket=AWS_BUCKET_NAME,
            CopySource={'Bucket': AWS_BUCKET_NAME, 'Key': submission.pending_file_path},
            Key=new_s3_key,
            ExtraArgs={'ContentType': 'application/pdf'}
        )
        
        # 3. Create the new Ebook record in the database
        new_ebook = Ebook(
            title=submission.title,
            author_name=submission.author,
            file_path=new_s3_key, # The new, public S3 key
            category_id=category_id,
            submitted_by_id=submission.submitted_by_id
        )
        db.session.add(new_ebook)

        # 4. Update the submission status
        submission.status = 'approved'
        
        # 5. Commit changes to DB
        db.session.commit()
        
        # 6. Delete the old pending file from S3
        s3_client.delete_object(
            Bucket=AWS_BUCKET_NAME, 
            Key=submission.pending_file_path
        )
        
        flash(f'"{submission.title}" has been approved and added to the library.', 'success')
    except Exception as e:
        db.session.rollback()
        print(f"[!] Error approving submission: {e}")
        flash(f'Error approving submission: {e}', 'danger')
    
    return redirect(url_for('submission_queue'))

@app.route('/admin/reject-submission/<int:sub_id>', methods=['POST'])
@admin_required
def reject_submission(sub_id):
    submission = db.session.get(BookSubmission, sub_id)
    if not submission:
        flash('Submission not found.', 'danger')
        return redirect(url_for('submission_queue'))
        
    try:
        # 1. Delete the pending file from S3
        if s3_client and submission.pending_file_path:
            s3_client.delete_object(
                Bucket=AWS_BUCKET_NAME, 
                Key=submission.pending_file_path
            )
            
        # 2. Update status (or delete the record)
        submission.status = 'rejected'
        db.session.commit()
        flash(f'Submission "{submission.title}" has been rejected and its file was deleted.', 'success')
    except Exception as e:
        db.session.rollback()
        print(f"[!] Error rejecting submission: {e}")
        flash(f'Error rejecting submission: {e}', 'danger')
        
    return redirect(url_for('submission_queue'))

@app.route('/admin/view-pending/<int:sub_id>')
@admin_required
def view_pending_file(sub_id):
    """
    Generates a secure, temporary S3 URL for a file in the
    pending-uploads/ directory.
    """
    if not s3_client:
        flash('Cloud storage (S3) is not configured.', 'danger')
        return redirect(url_for('submission_queue'))

    submission = db.session.get(BookSubmission, sub_id)
    if not submission or not submission.pending_file_path:
        flash('Pending file reference not found.', 'danger')
        return redirect(url_for('submission_queue'))

    try:
        read_url = s3_client.generate_presigned_url(
            'get_object',
            Params={
                'Bucket': AWS_BUCKET_NAME, 
                'Key': submission.pending_file_path,
                'ResponseContentDisposition': 'inline' 
            },
            ExpiresIn=3600  # Valid for 1 hour
        )
        return redirect(read_url)
    except Exception as e:
        print(f"[!] Error generating pre-signed URL for pending file: {e}")
        flash(f'Error retrieving file: {e}', 'danger')
        return redirect(url_for('submission_queue'))

@app.route('/admin/add-category', methods=['POST'])
@admin_required
def add_category():
    name = request.form.get('category_name')
    if name:
        try:
            new_category = Category(name=name)
            db.session.add(new_category)
            db.session.commit()
            flash(f'Category "{name}" has been added.', 'success')
        except Exception as e:
            db.session.rollback()
            flash(f'Error adding category (it might already exist): {e}', 'danger')
    else:
        flash('Category name cannot be empty.', 'danger')
    return redirect(url_for('admin_dashboard'))

@app.route('/admin/delete-category/<int:category_id>', methods=['POST'])
@admin_required
def delete_category(category_id):
    category_to_delete = db.session.get(Category, category_id)
    if not category_to_delete:
        flash('Category not found.', 'danger')
        return redirect(url_for('admin_dashboard'))
    
    # Check if any ebooks are using this category
    ebooks_in_category = Ebook.query.filter_by(category_id=category_id).count()
    if ebooks_in_category > 0:
        flash('Cannot delete category: Ebooks are still assigned to it.', 'warning')
        return redirect(url_for('admin_dashboard'))

    try:
        db.session.delete(category_to_delete)
        db.session.commit()
        flash(f'Category "{category_to_delete.name}" deleted.', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Error deleting category: {e}', 'danger')
    return redirect(url_for('admin_dashboard'))

@app.route('/submit-book', methods=['GET', 'POST'])
@login_required
def submit_book():
    """
    Handles user book submission.
    1. Uploads file to S3 'pending-uploads/'
    2. Triggers AI genuineness check
    3. Triggers AI categorization
    4. IF (Genuine AND Category found) -> Auto-publish
    5. ELSE -> Send to admin review queue
    """
    if request.method == 'POST':
        title = request.form.get('title')
        author = request.form.get('author')
        ebook_file = request.files.get('ebook_file')

        if not title or not author or not ebook_file:
            flash('Title, Author, and a PDF file are required.', 'danger')
            return redirect(url_for('submit_book'))

        if not s3_client:
            flash('Cloud storage is not configured. Cannot process submission.', 'danger')
            return redirect(url_for('submit_book'))

        if not ebook_file.filename.lower().endswith('.pdf'):
            flash('Invalid file. Only PDF files are allowed.', 'danger')
            return redirect(url_for('submit_book'))

        # --- 1. S3 Upload (to pending) ---
        filename = secure_filename(f"user_{session['user_id']}_{ebook_file.filename}")
        pending_s3_key = f"pending-uploads/{filename}"

        try:
            s3_client.upload_fileobj(
                ebook_file,
                AWS_BUCKET_NAME,
                pending_s3_key,
                ExtraArgs={'ContentType': 'application/pdf'}
            )
        except Exception as e:
            print(f"[!] Error uploading to S3: {e}")
            flash(f'Error uploading file to cloud storage: {e}', 'danger')
            return redirect(url_for('submit_book'))

        try:
            # --- 2. AI Genuineness Check ---
            extracted_text = ai_tools.extract_text_from_pdf_strategically(s3_client, AWS_BUCKET_NAME, pending_s3_key)
            genuineness_verdict = ai_tools.check_book_genuineness(title, author, extracted_text)

            # --- 3. AI Categorization ---
            all_categories = Category.query.all()
            category_names = [c.name for c in all_categories]
            ai_category_name = ai_tools.categorize_book(extracted_text, category_names)
            ai_category = Category.query.filter_by(name=ai_category_name).first()

            # --- 4. The "Auto-Publish" Logic ---
            if genuineness_verdict == "Genuine" and ai_category:
                # --- AUTO-PUBLISH ---
                print(f"[!] AI Auto-Approval: Verdict={genuineness_verdict}, Category={ai_category_name}")
                
                # 1. Define new S3 key (moving it out of 'pending-uploads/')
                new_s3_key = filename
                
                # 2. Copy the object in S3
                s3_client.copy_object(
                    Bucket=AWS_BUCKET_NAME,
                    CopySource={'Bucket': AWS_BUCKET_NAME, 'Key': pending_s3_key},
                    Key=new_s3_key,
                    ExtraArgs={'ContentType': 'application/pdf'}
                )
                
                # 3. Create the new Ebook record
                new_ebook = Ebook(
                    title=title,
                    author_name=author,
                    file_path=new_s3_key,
                    category_id=ai_category.id,
                    submitted_by_id=session['user_id']
                )
                db.session.add(new_ebook)
                db.session.commit()
                
                # 4. Delete the old pending file
                s3_client.delete_object(Bucket=AWS_BUCKET_NAME, Key=pending_s3_key)
                
                # 5. Send Admin Email (FYI)
                mail.send(Message(
                    subject=f"[Public Index] AI Auto-Published Book: {title}",
                    sender=app.config['MAIL_USERNAME'],
                    recipients=[app.config['MAIL_USERNAME']],
                    body=f"A new book was auto-published by the AI.\n\n"
                         f"Title: {title}\n"
                         f"Author: {author}\n"
                         f"Submitter: {session['username']}\n"
                         f"AI Verdict: {genuineness_verdict}\n"
                         f"AI Category: {ai_category_name}\n\n"
                         f"No action is required."
                ))
                
                flash('Success! Your book was verified by AI and added to the library.', 'success')
            
            else:
                # --- FALLBACK TO ADMIN REVIEW ---
                print(f"[!] AI Fallback: Verdict={genuineness_verdict}, Category={ai_category_name}")
                ai_review = f"AI Verdict: {genuineness_verdict}\nAI Category Guess: {ai_category_name}"
                
                # 1. Save submission to our database
                new_submission = BookSubmission(
                    title=title,
                    author=author,
                    submitted_by_id=session['user_id'],
                    pending_file_path=pending_s3_key,
                    ai_analysis=ai_review
                )
                db.session.add(new_submission)
                db.session.commit()

                # 2. Send Admin Email (Action Required)
                mail.send(Message(
                    subject=f"[Public Index] New Book Needs Review: {title}",
                    sender=app.config['MAIL_USERNAME'],
                    recipients=[app.config['MAIL_USERNAME']],
                    body=f"A new book submission from {session['username']} failed AI checks and needs manual review.\n\n"
                         f"Title: {title}\n"
                         f"Author: {author}\n\n"
                         f"AI ANALYSIS:\n{ai_review}\n\n"
                         f"Please log in to the admin panel to approve or reject."
                ))
                
                flash('Thank you! Your book has been submitted for admin review.', 'success')

            return redirect(url_for('dashboard'))

        except Exception as e:
            db.session.rollback()
            print(f"[!] Error in AI processing or DB save: {e}")
            # Try to delete the orphaned S3 file
            try:
                s3_client.delete_object(Bucket=AWS_BUCKET_NAME, Key=pending_s3_key)
            except Exception as s3_e:
                print(f"[!] Failed to delete orphaned S3 file {pending_s3_key}: {s3_e}")
            
            flash(f'Error during AI analysis: {e}', 'danger')
            return redirect(url_for('submit_book'))

    # GET request
    return render_template('submit_book.html')

# --- User Dashboard & Book Access Routes ---

@app.route('/')
@login_required
def dashboard():
    """
    Shows the main library dashboard.
    Fetches all books and categories for display.
    """
    try:
        # Fetch all books and categories, ordered alphabetically
        ebooks = Ebook.query.order_by(Ebook.title).all()
        categories = Category.query.order_by(Category.name).all()
    except Exception as e:
        flash(f'Error fetching library data: {e}', 'danger')
        ebooks = []
        categories = []
        
    return render_template(
        'dashboard.html', 
        ebooks=ebooks, 
        categories=categories,
        logged_in='logged_in' in session 
    )

@app.route('/api/search')
@login_required
def api_search():
    """
    API endpoint for the live search bar on the dashboard.
    Searches title, author, and category.
    Returns JSON.
    """
    search_query = request.args.get('q', '')
    category_id = request.args.get('category', '')
    
    # Start with a base query
    query = Ebook.query
    
    # Apply search filter if 'q' is provided
    if search_query:
        search_term = f'%{search_query}%'
        query = query.filter(
            or_(
                Ebook.title.ilike(search_term),
                Ebook.author_name.ilike(search_term)
            )
        )
        
    # Apply category filter if 'category' is provided
    if category_id:
        query = query.filter(Ebook.category_id == category_id)
        
    ebooks = query.order_by(Ebook.title).all()
    
    # Format the results as JSON
    results = [
        {
            'id': e.id,
            'title': e.title,
            'author_name': e.author_name,
            'category_name': e.category.name if e.category else 'N/A',
            'cover_image_url': e.cover_image_url
            # We will use this ID for the read button link
        } 
        for e in ebooks
    ]
    return jsonify(results)

@app.route('/read/<int:ebook_id>')
@login_required
def read_ebook(ebook_id):
    """
    Generates a secure, temporary S3 URL and redirects the user
    to the in-browser PDF viewer.
    This is for *reading*, not downloading.
    """
    if not s3_client:
        flash('Cloud storage (S3) is not configured.', 'danger')
        return redirect(url_for('dashboard'))

    ebook = db.session.get(Ebook, ebook_id)
    if not ebook or not ebook.file_path:
        flash('Book file reference not found.', 'danger')
        return redirect(url_for('dashboard'))

    try:
        s3_key = ebook.file_path 

        # Generate a pre-signed URL to GET the object
        # This URL is temporary and secure
        read_url = s3_client.generate_presigned_url(
            'get_object',
            Params={
                'Bucket': AWS_BUCKET_NAME, 
                'Key': s3_key,
                # This hint tells the browser to display it inline
                'ResponseContentDisposition': 'inline' 
            },
            ExpiresIn=3600  # URL is valid for 1 hour (3600 seconds)
        )

        # Redirect the user's browser to the S3 URL
        # We will build the 'ebook_reader.html' template later
        # For now, let's redirect directly to the PDF
        # return redirect(read_url)
        
        # --- NEW ---
        # Instead of just redirecting, let's send them to our reader template
        # Our reader.js will then load the PDF from this URL
        return render_template(
            'reader/ebook_reader.html', 
            ebook=ebook, 
            s3_read_url=read_url
        )

    except Exception as e:
        print(f"[!] Error generating S3 pre-signed URL for key '{s3_key}': {e}")
        flash(f'Error retrieving file from cloud storage: {e}', 'danger')
        return redirect(url_for('dashboard'))

@app.route('/download/<int:ebook_id>')
@login_required 
def download_ebook(ebook_id):
    """
    Generates a secure, temporary S3 URL that forces a
    'Save As...' download prompt.
    """
    if not s3_client:
        flash('Cloud storage (S3) is not configured.', 'danger')
        return redirect(url_for('dashboard'))

    ebook = db.session.get(Ebook, ebook_id)
    if not ebook or not ebook.file_path:
        flash('Book file reference not found.', 'danger')
        return redirect(url_for('dashboard'))

    try:
        s3_key = ebook.file_path 

        # Generate a pre-signed URL that FORCES download
        download_url = s3_client.generate_presigned_url(
            'get_object',
            Params={
                'Bucket': AWS_BUCKET_NAME, 
                'Key': s3_key,
                # This tells the browser to treat it as an attachment
                'ResponseContentDisposition': f'attachment; filename="{s3_key}"' 
            },
            ExpiresIn=3600  # URL is valid for 1 hour
        )
        
        # Redirect to the S3 URL
        return redirect(download_url)
        
    except Exception as e:
        print(f"[!] Error generating S3 pre-signed URL for key '{s3_key}': {e}")
        flash(f'Error retrieving file from cloud storage: {e}', 'danger')
        return redirect(url_for('dashboard'))

# --- Contact Route (Reused from your project) ---

@app.route('/contact', methods=['GET', 'POST'])
@login_required
def contact():
    if request.method == 'POST':
        email = request.form['email']
        subject = request.form['subject']
        message_body = request.form['message']
        
        # Get username from session
        username = session.get('username', 'Logged-in User')

        try:
            msg = Message(
                subject=f"[Public Index Support] {subject}",
                sender=app.config['MAIL_USERNAME'],
                recipients=[app.config['MAIL_USERNAME']] # Admin's email
            )
            msg.body = f"""
New Support Message
From: {username} ({email})
Subject: {subject}

Message:
{message_body}
"""
            mail.send(msg)
            
            # Save to database
            new_support_msg = SupportMessage(
                username=username,
                email=email,
                subject=subject,
                message=message_body
            )
            db.session.add(new_support_msg)
            db.session.commit()
            
            flash('Your message has been sent successfully! We will get back to you soon.', 'success')
        
        except Exception as e:
            db.session.rollback()
            print(f"[!] Error sending contact email: {e}")
            flash(f'An error occurred while sending your message: {e}', 'danger')

        return redirect(url_for('contact'))

    return render_template('contact.html')

# --- Annotation & Layer API Routes ---
# These routes will be called by JavaScript (reader.js) from the 
# 'ebook_reader.html' template to make it dynamic.

@app.route('/api/book/<int:ebook_id>/layers')
@login_required
def get_layers_for_book(ebook_id):
    """
    API: Fetches all annotation layers for a given ebook that the user has access to.
    (Public layers, user's own layers, or layers from user's groups).
    """
    try:
        user = db.session.get(User, session['user_id'])
        # Get a list of the user's group IDs
        user_group_ids = [group.id for group in user.study_groups]

        # Fetch layers that are:
        # 1. Public, OR
        # 2. Created by the current user, OR
        # 3. Part of a group the user is in.
        layers = AnnotationLayer.query.filter(
            AnnotationLayer.ebook_id == ebook_id,
            or_(
                AnnotationLayer.is_public == True,
                AnnotationLayer.creator_id == user.id,
                AnnotationLayer.study_group_id.in_(user_group_ids)
            )
        ).order_by(AnnotationLayer.name).all()

        results = [
            {
                'id': layer.id,
                'name': layer.name,
                'description': layer.description,
                'creator_id': layer.creator_id,
                'creator_name': layer.creator.username,
                'is_public': layer.is_public
            }
            for layer in layers
        ]
        return jsonify(results)
    except Exception as e:
        print(f"[!] Error fetching layers: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/layer/<int:layer_id>/annotations')
@login_required
def get_annotations_for_layer(layer_id):
    """
    API: Fetches all annotations within a specific layer.
    """
    try:
        annotations = Annotation.query.filter_by(layer_id=layer_id).order_by(Annotation.timestamp.asc()).all()
        
        results = [
            {
                'id': annotation.id,
                'content': annotation.content,
                'highlighted_text': annotation.highlighted_text,
                'position_data': annotation.position_data,
                'author_id': annotation.author_id,
                'author_name': annotation.author.username,
                'timestamp': annotation.timestamp.isoformat()
            }
            for annotation in annotations
        ]
        return jsonify(results)
    except Exception as e:
        print(f"[!] Error fetching annotations: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/annotation/new', methods=['POST'])
@login_required
def create_annotation():
    """
    API: Creates a new annotation.
    Expects JSON data from our reader.js.
    """
    data = request.json
    if not data or 'content' not in data or 'layer_id' not in data:
        return jsonify({'error': 'Missing required data'}), 400

    try:
        new_annotation = Annotation(
            content=data['content'],
            layer_id=data['layer_id'],
            author_id=session['user_id'],
            highlighted_text=data.get('highlighted_text'),
            position_data=data.get('position_data') # e.g., chapter/paragraph
        )
        db.session.add(new_annotation)
        db.session.commit()
        
        # Return the new annotation so the frontend can display it
        return jsonify({
            'id': new_annotation.id,
            'content': new_annotation.content,
            'highlighted_text': new_annotation.highlighted_text,
            'position_data': new_annotation.position_data,
            'author_id': new_annotation.author_id,
            'author_name': new_annotation.author.username,
            'timestamp': new_annotation.timestamp.isoformat()
        }), 201 # 201 = Created
        
    except Exception as e:
        db.session.rollback()
        print(f"[!] Error creating annotation: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/annotation/<int:annotation_id>/delete', methods=['POST']) # Use POST for deletion
@login_required
def delete_annotation(annotation_id):
    """
    API: Deletes an annotation.
    Ensures only the author or an admin can delete it.
    """
    try:
        annotation = db.session.get(Annotation, annotation_id)
        if not annotation:
            return jsonify({'error': 'Annotation not found'}), 404

        # Check permission
        if annotation.author_id != session['user_id'] and not session['is_admin']:
            return jsonify({'error': 'You do not have permission to delete this'}), 403

        db.session.delete(annotation)
        db.session.commit()
        return jsonify({'success': True, 'message': 'Annotation deleted'}), 200
        
    except Exception as e:
        db.session.rollback()
        print(f"[!] Error deleting annotation: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/layer/new', methods=['POST'])
@login_required
def create_layer():
    """
    API: Creates a new annotation layer for a book.
    Can now be public OR linked to a study group.
    """
    data = request.json
    if not data or 'name' not in data or 'ebook_id' not in data:
        return jsonify({'error': 'Missing required data (name, ebook_id)'}), 400
    
    study_group_id = data.get('study_group_id')
    is_public = not bool(study_group_id) # A layer is public if it's NOT for a group

    # Security Check: If a group ID is provided, ensure user is a member.
    if study_group_id:
        # We need to get the User object to check the relationship
        user = db.session.get(User, session['user_id'])
        is_member = user.study_groups.filter_by(id=study_group_id).first()
        if not is_member:
            return jsonify({'error': 'You are not a member of this group'}), 403

    try:
        new_layer = AnnotationLayer(
            name=data['name'],
            ebook_id=data['ebook_id'],
            creator_id=session['user_id'],
            description=data.get('description'),
            is_public=is_public,
            study_group_id=study_group_id # <-- This is the new field
        )
        db.session.add(new_layer)
        db.session.commit()
        
        # Return the new layer object
        return jsonify({
            'id': new_layer.id,
            'name': new_layer.name,
            'description': new_layer.description,
            'creator_id': new_layer.creator_id,
            'creator_name': new_layer.creator.username,
            'is_public': new_layer.is_public
        }), 201

    except Exception as e:
        db.session.rollback()
        print(f"[!] Error creating layer: {e}")
        return jsonify({'error': str(e)}), 500
    
# --- App Execution ---

# --- Study Group Routes ---

@app.route('/groups')
@login_required
def group_list():
    """
    Shows the list of all study groups and the 'Create' form.
    Supports searching by name.
    """
    search_query = request.args.get('q', '').strip()
    
    try:
        query = StudyGroup.query
        if search_query:
            # Filter by name (case-insensitive)
            search_term = f"%{search_query}%"
            query = query.filter(StudyGroup.name.ilike(search_term))
            
        groups = query.order_by(StudyGroup.name).all()
        
    except Exception as e:
        flash(f"Error fetching groups: {e}", "danger")
        groups = []
        
    return render_template(
        'groups/group_list.html', 
        groups=groups, 
        search_query=search_query,
        current_user_id=session['user_id']
    )

@app.route('/groups/create', methods=['POST'])
@login_required
def create_group():
    """
    Handles the form submission for creating a new group.
    Enforces unique group names.
    """
    name = request.form.get('name')
    description = request.form.get('description')
    
    if not name:
        flash("Group name is required.", "danger")
        return redirect(url_for('group_list'))
    
    # --- Check for existing group name ---
    existing_group = StudyGroup.query.filter_by(name=name).first()
    if existing_group:
        flash(f"A group with the name '{name}' already exists. Please choose a different name.", "warning")
        return redirect(url_for('group_list'))
    
    try:
        # Create the new group
        new_group = StudyGroup(
            name=name,
            description=description,
            creator_id=session['user_id']
        )
        db.session.add(new_group)
        
        # The creator is automatically a member.
        creator = db.session.get(User, session['user_id'])
        new_group.members.append(creator)
        
        db.session.commit()
        flash(f"Group '{name}' created successfully!", "success")
        return redirect(url_for('group_detail', group_id=new_group.id))
        
    except Exception as e:
        db.session.rollback()
        flash(f"Error creating group: {e}", "danger")
        return redirect(url_for('group_list'))


@app.route('/api/groups/search')
@login_required
def api_search_groups():
    """
    API: Returns a JSON list of groups matching the search query.
    Includes 'is_member' status so the frontend knows whether to show 'Join' or 'View'.
    """
    query_text = request.args.get('q', '').strip()
    current_user = db.session.get(User, session['user_id'])
    
    try:
        query = StudyGroup.query
        if query_text:
            # Filter by name (case-insensitive)
            search_term = f"%{query_text}%"
            query = query.filter(StudyGroup.name.ilike(search_term))
        
        # Order alphabetically
        groups = query.order_by(StudyGroup.name).all()
        
        # Build JSON response
        results = []
        for group in groups:
            # Check if current user is in this group
            is_member = group.members.filter(User.id == current_user.id).first() is not None
            
            results.append({
                'id': group.id,
                'name': group.name,
                'creator_name': group.creator.username,
                'member_count': group.members.count(),
                'is_member': is_member
            })
            
        return jsonify(results)
        
    except Exception as e:
        print(f"[!] Error searching groups: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/group/<int:group_id>')
@login_required
def group_detail(group_id):
    """
    Shows the detail page for a single study group.
    """
    group = db.session.get(StudyGroup, group_id)
    if not group:
        flash("Group not found.", "danger")
        return redirect(url_for('group_list'))
    
    # Check if current user is a member
    is_member = group.members.filter(User.id == session['user_id']).first()
    if not is_member and not session.get('is_admin'):
        flash("You are not a member of this group.", "warning")
        return redirect(url_for('group_list'))
        
    return render_template('groups/group_detail.html', group=group)

@app.route('/group/<int:group_id>/join', methods=['POST'])
@login_required
def join_group(group_id):
    group = db.session.get(StudyGroup, group_id)
    user = db.session.get(User, session['user_id'])
    
    if not group:
        flash("Group not found.", "danger")
        return redirect(url_for('group_list'))
    
    # Check if user is already a member
    is_member = group.members.filter(User.id == user.id).first()
    if is_member:
        flash("You are already a member of this group.", "info")
    else:
        try:
            group.members.append(user)
            db.session.commit()
            flash(f"Welcome to '{group.name}'!", "success")
        except Exception as e:
            db.session.rollback()
            flash(f"Error joining group: {e}", "danger")
            
    return redirect(url_for('group_detail', group_id=group.id))

@app.route('/group/<int:group_id>/leave', methods=['POST'])
@login_required
def leave_group(group_id):
    group = db.session.get(StudyGroup, group_id)
    user = db.session.get(User, session['user_id'])

    if not group:
        flash("Group not found.", "danger")
        return redirect(url_for('group_list'))

    # Check if user is a member
    is_member = group.members.filter(User.id == user.id).first()
    if not is_member:
        flash("You are not a member of this group.", "info")
        return redirect(url_for('group_list'))

    # Prevent creator from leaving
    if group.creator_id == user.id:
        flash("As the group creator, you cannot leave the group. You can delete it (feature to be added).", "warning")
        return redirect(url_for('group_detail', group_id=group.id))

    try:
        group.members.remove(user)
        db.session.commit()
        flash(f"You have left '{group.name}'.", "success")
    except Exception as e:
        db.session.rollback()
        flash(f"Error leaving group: {e}", "danger")
        
    return redirect(url_for('group_list'))


@app.route('/group/<int:group_id>/delete', methods=['POST'])
@login_required
def delete_group(group_id):
    """
    Allows the creator (or admin) to delete a study group.
    """
    group = db.session.get(StudyGroup, group_id)
    if not group:
        flash("Group not found.", "danger")
        return redirect(url_for('group_list'))
    
    # Authorization Check
    # Only the Creator or an Admin can delete the group
    if group.creator_id != session['user_id'] and not session.get('is_admin'):
        flash("You do not have permission to delete this group.", "danger")
        return redirect(url_for('group_detail', group_id=group.id))

    try:
        # 1. Optional: Clean up layers associated with this group
        # We'll set them to 'private' (study_group_id=None) so the data isn't lost,
        # or you could delete them with .delete() if you prefer.
        associated_layers = AnnotationLayer.query.filter_by(study_group_id=group.id).all()
        for layer in associated_layers:
            layer.study_group_id = None # Unlink them, making them private to the author
            # OR: db.session.delete(layer) # To delete them entirely
        
        # 2. Delete the group
        db.session.delete(group)
        db.session.commit()
        flash(f"Group '{group.name}' has been successfully deleted.", "success")
    except Exception as e:
        db.session.rollback()
        print(f"[!] Error deleting group: {e}")
        flash(f"Error deleting group: {e}", "danger")
        return redirect(url_for('group_detail', group_id=group.id))

    return redirect(url_for('group_list'))

@app.route('/api/user/groups')
@login_required
def get_user_groups():
    """
    API: Fetches all study groups the current user is a member of.
    """
    try:
        user = db.session.get(User, session['user_id'])
        groups = user.study_groups.order_by(StudyGroup.name).all()
        
        results = [
            {'id': group.id, 'name': group.name}
            for group in groups
        ]
        return jsonify(results)
    except Exception as e:
        print(f"[!] Error fetching user groups: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/layer/<int:layer_id>/summarize')
@login_required
def summarize_layer(layer_id):
    """
    API: Calls AI to summarize all annotations in a given layer.
    """
    try:
        layer = db.session.get(AnnotationLayer, layer_id)
        if not layer:
            return jsonify({'error': 'Layer not found'}), 404
        
        # Check if user has access (public, creator, or group member)
        # For now, we'll just check if they are logged in
        
        summary_data = ai_tools.summarize_annotations(layer)
        
        if summary_data.get('error'):
            return jsonify(summary_data), 500
            
        return jsonify(summary_data)
        
    except Exception as e:
        print(f"[!] Error summarizing annotations: {e}")
        return jsonify({'error': str(e)}), 500

def fetch_book_cover(title, author):
    """
    Searches Google Books API for a cover image URL.
    """
    try:
        # Construct search query
        query = f"intitle:{title}+inauthor:{author}"
        api_url = f"https://www.googleapis.com/books/v1/volumes?q={query}&maxResults=1"
        
        response = requests.get(api_url)
        data = response.json()
        
        if "items" in data and len(data["items"]) > 0:
            volume_info = data["items"][0].get("volumeInfo", {})
            image_links = volume_info.get("imageLinks", {})
            
            # Try to get largest available, fallback to thumbnail
            img_url = image_links.get("thumbnail") or image_links.get("smallThumbnail")
            
            if img_url:
                # Ensure it uses HTTPS (Google sometimes returns http)
                return img_url.replace("http://", "https://")
                
        return None # No image found
        
    except Exception as e:
        print(f"[!] Error fetching book cover: {e}")
        return None
if __name__ == '__main__':
    with app.app_context():
        db.create_all() # Creates tables from models.py if they don't exist
    app.run(debug=True)