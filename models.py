from flask_sqlalchemy import SQLAlchemy
from flask_bcrypt import Bcrypt
from sqlalchemy.sql import func
import json

# Initialize extensions
db = SQLAlchemy()
bcrypt = Bcrypt()

# --- Association Table ---
# This is a helper table for our many-to-many relationship
# It links Users to the StudyGroups they are members of.
user_study_group = db.Table('user_study_group',
    db.Column('user_id', db.Integer, db.ForeignKey('user.id'), primary_key=True),
    db.Column('group_id', db.Integer, db.ForeignKey('study_group.id'), primary_key=True)
)

# --- Core Models ---

class User(db.Model):
    """
    Combines Customer, Login, and CustomerDetails from your original project
    into a single, cleaner User model.
    """
    __tablename__ = 'user'
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    first_name = db.Column(db.String(50), nullable=True)
    last_name = db.Column(db.String(50), nullable=True)
    is_admin = db.Column(db.Boolean, default=False, nullable=False)
    
    # Relationships
    # 'creator' is used when a user is the single owner of an item
    # 'author' is used for annotations
    
    # This user is the creator of these study groups
    created_groups = db.relationship('StudyGroup', backref='creator', lazy=True)
    # This user is the creator of these layers
    created_layers = db.relationship('AnnotationLayer', backref='creator', lazy=True)
    # This user is the author of these annotations
    annotations = db.relationship('Annotation', backref='author', lazy=True)
    # This user submitted these books
    submitted_books = db.relationship('Ebook', backref='submitter', lazy=True)
    
    # Many-to-many relationship for group membership
    study_groups = db.relationship('StudyGroup', secondary=user_study_group,
                                 back_populates='members', lazy='dynamic')

    def set_password(self, password):
        self.password_hash = bcrypt.generate_password_hash(password).decode('utf-8')

    def check_password(self, password):
        return bcrypt.check_password_hash(self.password_hash, password)

class Category(db.Model):
    """
    KEPT FROM YOUR PROJECT:
    Stores the categories for books (e.g., "Philosophy", "Physics").
    """
    __tablename__ = 'category'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(80), nullable=False, unique=True)
    description = db.Column(db.Text, nullable=True)
    
    ebooks = db.relationship('Ebook', backref='category', lazy=True)

class Ebook(db.Model):
    """
    ADAPTED FROM YOUR PROJECT:
    Represents a book in the public library.
    'price' has been removed.
    'file_path' now refers to the S3 object key.
    'submitted_by_id' links to the user who submitted it (can be an admin).
    """
    __tablename__ = 'ebook'
    id = db.Column(db.Integer, primary_key=True)  # <--- THIS LINE IS THE IMPORTANT ONE
    title = db.Column(db.String(200), nullable=False)
    author_name = db.Column(db.String(150), nullable=False)
    file_path = db.Column(db.String(255), nullable=False) # S3 Key
    category_id = db.Column(db.Integer, db.ForeignKey('category.id'), nullable=False)
    submitted_by_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    text_content = db.Column(db.Text, nullable=True)
    cover_image_url = db.Column(db.Text, nullable=True)
    # Relationships
    layers = db.relationship('AnnotationLayer', backref='ebook', lazy=True, cascade="all, delete-orphan")

# --- New Models for "The Public Index" ---

class StudyGroup(db.Model):
    """
    NEW MODEL:
    A group created by a user for collaborative study.
    """
    __tablename__ = 'study_group'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    description = db.Column(db.Text, nullable=True)
    creator_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    
    # Many-to-many relationship for group members
    members = db.relationship('User', secondary=user_study_group,
                              back_populates='study_groups', lazy='dynamic')
    # Layers associated with this group
    layers = db.relationship('AnnotationLayer', backref='study_group', lazy=True)

class AnnotationLayer(db.Model):
    """
    NEW MODEL:
    A named "layer" for annotations (e.g., "Historical Context").
    It belongs to one Ebook and is created by one User.
    It can optionally be linked to a StudyGroup.
    """
    __tablename__ = 'annotation_layer'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    description = db.Column(db.Text, nullable=True)
    is_public = db.Column(db.Boolean, default=True, nullable=False)
    
    creator_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    ebook_id = db.Column(db.Integer, db.ForeignKey('ebook.id'), nullable=False)
    # A layer can be private to a study group
    study_group_id = db.Column(db.Integer, db.ForeignKey('study_group.id'), nullable=True) 
    
    annotations = db.relationship('Annotation', backref='layer', lazy=True, cascade="all, delete-orphan")

class Annotation(db.Model):
    """
    NEW MODEL:
    A single note or highlight made by a user.
    It belongs to one Layer and is authored by one User.
    """
    __tablename__ = 'annotation'
    id = db.Column(db.Integer, primary_key=True)
    content = db.Column(db.Text, nullable=False) # The user's note
    highlighted_text = db.Column(db.Text, nullable=True) # The text they selected
    
    # Storing position data (e.g., CFI string or chapter/paragraph) as JSON
    position_data = db.Column(db.String(500), nullable=True) 
    
    author_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    layer_id = db.Column(db.Integer, db.ForeignKey('annotation_layer.id'), nullable=False)
    timestamp = db.Column(db.DateTime(timezone=True), server_default=func.now())

# --- Utility Models ---

class BookSubmission(db.Model):
    """
    NEW MODEL:
    A queue for users to suggest books for the library.
    Admins will review these.
    """
    __tablename__ = 'book_submission'
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    author = db.Column(db.String(150), nullable=False)
    source_url = db.Column(db.String(500), nullable=True) # e.g., link to Project Gutenberg
    
    # --- THESE FIELDS ARE REQUIRED FOR PHASE 2 ---
    pending_file_path = db.Column(db.String(500), nullable=True) # S3 key for the pending file
    ai_analysis = db.Column(db.Text, nullable=True) # To store Gemini's review
    
    status = db.Column(db.String(20), default='pending', nullable=False) # pending, approved, rejected
    submitted_by_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    timestamp = db.Column(db.DateTime(timezone=True), server_default=func.now())
    
    submitter = db.relationship('User', backref='submissions')


class SupportMessage(db.Model):
    """
    KEPT FROM YOUR PROJECT:
    For the '/contact' page.
    """
    __tablename__ = 'support_message'
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(100)) # Kept from original
    email = db.Column(db.String(120), nullable=False)
    subject = db.Column(db.String(200))
    message = db.Column(db.Text, nullable=False)
    timestamp = db.Column(db.DateTime(timezone=True), server_default=func.now())