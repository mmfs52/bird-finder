from flask import Flask, request, jsonify
from flask_sqlalchemy import SQLAlchemy
from flask_cors import CORS
from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime, timedelta
import os
import uuid
from PIL import Image
import base64
from io import BytesIO
import json

app = Flask(__name__)
CORS(app)

# Configuration
app.config['SECRET_KEY'] = 'your-secret-key-here'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///bird_finder.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['UPLOAD_FOLDER'] = 'uploads'
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max file size

db = SQLAlchemy(app)

# Create upload directory
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

# Database Models
class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(128))
    name = db.Column(db.String(80), nullable=False)
    phone = db.Column(db.String(20))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Relationships
    lost_birds = db.relationship('LostBird', backref='owner', lazy=True, foreign_keys='LostBird.user_id')
    found_birds = db.relationship('FoundBird', backref='finder', lazy=True)
    reports = db.relationship('SightingReport', backref='reporter', lazy=True)

class BirdSpecies(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name_th = db.Column(db.String(100), nullable=False)
    name_en = db.Column(db.String(100))
    description = db.Column(db.Text)
    characteristics = db.Column(db.Text)  # JSON string
    
class LostBird(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    species_id = db.Column(db.Integer, db.ForeignKey('bird_species.id'))
    
    # Bird details
    name = db.Column(db.String(100), nullable=False)
    description = db.Column(db.Text, nullable=False)
    characteristics = db.Column(db.Text)  # JSON string for colors, size, etc.
    photos = db.Column(db.Text)  # JSON array of photo URLs
    
    # Location and time
    last_seen_location = db.Column(db.String(200), nullable=False)
    last_seen_lat = db.Column(db.Float)
    last_seen_lng = db.Column(db.Float)
    lost_date = db.Column(db.DateTime, nullable=False)
    
    # Contact and reward
    contact_info = db.Column(db.Text)  # JSON string
    reward_amount = db.Column(db.Integer, default=0)  # in THB
    
    # Status
    status = db.Column(db.String(20), default='lost')  # lost, found, reunited
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    species = db.relationship('BirdSpecies', backref='lost_birds')
    sightings = db.relationship('SightingReport', backref='lost_bird', lazy=True)

class FoundBird(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    species_id = db.Column(db.Integer, db.ForeignKey('bird_species.id'))
    
    # Bird details
    description = db.Column(db.Text, nullable=False)
    characteristics = db.Column(db.Text)  # JSON string
    photos = db.Column(db.Text)  # JSON array of photo URLs
    
    # Location and time
    found_location = db.Column(db.String(200), nullable=False)
    found_lat = db.Column(db.Float)
    found_lng = db.Column(db.Float)
    found_date = db.Column(db.DateTime, nullable=False)
    
    # Contact
    contact_info = db.Column(db.Text)  # JSON string
    
    # Status
    status = db.Column(db.String(20), default='found')  # found, claimed
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Relationships
    species = db.relationship('BirdSpecies', backref='found_birds')

class SightingReport(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    lost_bird_id = db.Column(db.Integer, db.ForeignKey('lost_bird.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    
    # Sighting details
    location = db.Column(db.String(200), nullable=False)
    lat = db.Column(db.Float)
    lng = db.Column(db.Float)
    sighting_date = db.Column(db.DateTime, nullable=False)
    description = db.Column(db.Text)
    photos = db.Column(db.Text)  # JSON array
    confidence_level = db.Column(db.Integer, default=5)  # 1-10 scale
    
    # Status
    verified = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

# Utility Functions
def allowed_file(filename):
    ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif'}
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def save_uploaded_file(file):
    if file and allowed_file(file.filename):
        filename = secure_filename(file.filename)
        unique_filename = str(uuid.uuid4()) + '_' + filename
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], unique_filename)
        file.save(filepath)
        return unique_filename
    return None

def resize_image(filepath, max_size=800):
    """Resize image while maintaining aspect ratio"""
    with Image.open(filepath) as img:
        img.thumbnail((max_size, max_size), Image.Resampling.LANCZOS)
        img.save(filepath, optimize=True, quality=85)

# Authentication Routes
@app.route('/api/register', methods=['POST'])
def register():
    try:
        data = request.get_json()
        
        # Validate required fields
        required_fields = ['email', 'password', 'name']
        for field in required_fields:
            if not data.get(field):
                return jsonify({'error': f'{field} is required'}), 400
        
        # Check if user already exists
        if User.query.filter_by(email=data['email']).first():
            return jsonify({'error': 'Email already registered'}), 400
        
        # Create new user
        user = User(
            email=data['email'],
            password_hash=generate_password_hash(data['password']),
            name=data['name'],
            phone=data.get('phone', '')
        )
        
        db.session.add(user)
        db.session.commit()
        
        return jsonify({
            'message': 'User registered successfully',
            'user_id': user.id
        }), 201
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/login', methods=['POST'])
def login():
    try:
        data = request.get_json()
        user = User.query.filter_by(email=data.get('email')).first()
        
        if user and check_password_hash(user.password_hash, data.get('password')):
            return jsonify({
                'message': 'Login successful',
                'user_id': user.id,
                'name': user.name
            }), 200
        
        return jsonify({'error': 'Invalid credentials'}), 401
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# Lost Birds Routes
@app.route('/api/lost-birds', methods=['POST'])
def create_lost_bird():
    try:
        data = request.get_json()
        
        # Validate required fields
        required_fields = ['user_id', 'name', 'description', 'last_seen_location', 'lost_date']
        for field in required_fields:
            if not data.get(field):
                return jsonify({'error': f'{field} is required'}), 400
        
        # Parse lost_date
        lost_date = datetime.fromisoformat(data['lost_date'].replace('Z', '+00:00'))
        
        lost_bird = LostBird(
            user_id=data['user_id'],
            species_id=data.get('species_id'),
            name=data['name'],
            description=data['description'],
            characteristics=json.dumps(data.get('characteristics', {})),
            photos=json.dumps(data.get('photos', [])),
            last_seen_location=data['last_seen_location'],
            last_seen_lat=data.get('last_seen_lat'),
            last_seen_lng=data.get('last_seen_lng'),
            lost_date=lost_date,
            contact_info=json.dumps(data.get('contact_info', {})),
            reward_amount=data.get('reward_amount', 0)
        )
        
        db.session.add(lost_bird)
        db.session.commit()
        
        return jsonify({
            'message': 'Lost bird report created successfully',
            'id': lost_bird.id
        }), 201
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/lost-birds', methods=['GET'])
def get_lost_birds():
    try:
        page = request.args.get('page', 1, type=int)
        per_page = request.args.get('per_page', 20, type=int)
        status = request.args.get('status', 'lost')
        
        query = LostBird.query.filter_by(status=status)
        
        # Search filters
        search = request.args.get('search')
        if search:
            query = query.filter(
                LostBird.name.contains(search) | 
                LostBird.description.contains(search) |
                LostBird.last_seen_location.contains(search)
            )
        
        # Location filter (within radius)
        lat = request.args.get('lat', type=float)
        lng = request.args.get('lng', type=float)
        radius = request.args.get('radius', 50, type=float)  # km
        
        if lat and lng:
            # Simple bounding box filter (more accurate would use Haversine formula)
            lat_range = radius / 111  # Approximate degrees per km
            lng_range = radius / (111 * abs(lat))
            
            query = query.filter(
                LostBird.last_seen_lat.between(lat - lat_range, lat + lat_range),
                LostBird.last_seen_lng.between(lng - lng_range, lng + lng_range)
            )
        
        pagination = query.order_by(LostBird.created_at.desc()).paginate(
            page=page, per_page=per_page, error_out=False
        )
        
        birds = []
        for bird in pagination.items:
            bird_data = {
                'id': bird.id,
                'name': bird.name,
                'description': bird.description,
                'characteristics': json.loads(bird.characteristics) if bird.characteristics else {},
                'photos': json.loads(bird.photos) if bird.photos else [],
                'last_seen_location': bird.last_seen_location,
                'last_seen_lat': bird.last_seen_lat,
                'last_seen_lng': bird.last_seen_lng,
                'lost_date': bird.lost_date.isoformat(),
                'reward_amount': bird.reward_amount,
                'status': bird.status,
                'created_at': bird.created_at.isoformat(),
                'owner': {
                    'name': bird.owner.name,
                    'phone': bird.owner.phone
                },
                'species': {
                    'name_th': bird.species.name_th,
                    'name_en': bird.species.name_en
                } if bird.species else None
            }
            birds.append(bird_data)
        
        return jsonify({
            'birds': birds,
            'pagination': {
                'page': page,
                'pages': pagination.pages,
                'total': pagination.total,
                'has_next': pagination.has_next,
                'has_prev': pagination.has_prev
            }
        }), 200
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/lost-birds/<int:bird_id>', methods=['GET'])
def get_lost_bird(bird_id):
    try:
        bird = LostBird.query.get_or_404(bird_id)
        
        bird_data = {
            'id': bird.id,
            'name': bird.name,
            'description': bird.description,
            'characteristics': json.loads(bird.characteristics) if bird.characteristics else {},
            'photos': json.loads(bird.photos) if bird.photos else [],
            'last_seen_location': bird.last_seen_location,
            'last_seen_lat': bird.last_seen_lat,
            'last_seen_lng': bird.last_seen_lng,
            'lost_date': bird.lost_date.isoformat(),
            'contact_info': json.loads(bird.contact_info) if bird.contact_info else {},
            'reward_amount': bird.reward_amount,
            'status': bird.status,
            'created_at': bird.created_at.isoformat(),
            'owner': {
                'id': bird.owner.id,
                'name': bird.owner.name,
                'email': bird.owner.email,
                'phone': bird.owner.phone
            },
            'species': {
                'id': bird.species.id,
                'name_th': bird.species.name_th,
                'name_en': bird.species.name_en,
                'description': bird.species.description
            } if bird.species else None,
            'sightings': [
                {
                    'id': s.id,
                    'location': s.location,
                    'lat': s.lat,
                    'lng': s.lng,
                    'sighting_date': s.sighting_date.isoformat(),
                    'description': s.description,
                    'photos': json.loads(s.photos) if s.photos else [],
                    'confidence_level': s.confidence_level,
                    'verified': s.verified,
                    'reporter': s.reporter.name
                }
                for s in bird.sightings
            ]
        }
        
        return jsonify(bird_data), 200
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# Found Birds Routes
@app.route('/api/found-birds', methods=['POST'])
def create_found_bird():
    try:
        data = request.get_json()
        
        required_fields = ['user_id', 'description', 'found_location', 'found_date']
        for field in required_fields:
            if not data.get(field):
                return jsonify({'error': f'{field} is required'}), 400
        
        found_date = datetime.fromisoformat(data['found_date'].replace('Z', '+00:00'))
        
        found_bird = FoundBird(
            user_id=data['user_id'],
            species_id=data.get('species_id'),
            description=data['description'],
            characteristics=json.dumps(data.get('characteristics', {})),
            photos=json.dumps(data.get('photos', [])),
            found_location=data['found_location'],
            found_lat=data.get('found_lat'),
            found_lng=data.get('found_lng'),
            found_date=found_date,
            contact_info=json.dumps(data.get('contact_info', {}))
        )
        
        db.session.add(found_bird)
        db.session.commit()
        
        return jsonify({
            'message': 'Found bird report created successfully',
            'id': found_bird.id
        }), 201
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/found-birds', methods=['GET'])
def get_found_birds():
    try:
        page = request.args.get('page', 1, type=int)
        per_page = request.args.get('per_page', 20, type=int)
        
        query = FoundBird.query.filter_by(status='found')
        
        pagination = query.order_by(FoundBird.created_at.desc()).paginate(
            page=page, per_page=per_page, error_out=False
        )
        
        birds = []
        for bird in pagination.items:
            bird_data = {
                'id': bird.id,
                'description': bird.description,
                'characteristics': json.loads(bird.characteristics) if bird.characteristics else {},
                'photos': json.loads(bird.photos) if bird.photos else [],
                'found_location': bird.found_location,
                'found_lat': bird.found_lat,
                'found_lng': bird.found_lng,
                'found_date': bird.found_date.isoformat(),
                'status': bird.status,
                'created_at': bird.created_at.isoformat(),
                'finder': {
                    'name': bird.finder.name,
                    'phone': bird.finder.phone
                }
            }
            birds.append(bird_data)
        
        return jsonify({
            'birds': birds,
            'pagination': {
                'page': page,
                'pages': pagination.pages,
                'total': pagination.total
            }
        }), 200
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# Sighting Reports Routes
@app.route('/api/sightings', methods=['POST'])
def create_sighting():
    try:
        data = request.get_json()
        
        required_fields = ['lost_bird_id', 'user_id', 'location', 'sighting_date']
        for field in required_fields:
            if not data.get(field):
                return jsonify({'error': f'{field} is required'}), 400
        
        sighting_date = datetime.fromisoformat(data['sighting_date'].replace('Z', '+00:00'))
        
        sighting = SightingReport(
            lost_bird_id=data['lost_bird_id'],
            user_id=data['user_id'],
            location=data['location'],
            lat=data.get('lat'),
            lng=data.get('lng'),
            sighting_date=sighting_date,
            description=data.get('description', ''),
            photos=json.dumps(data.get('photos', [])),
            confidence_level=data.get('confidence_level', 5)
        )
        
        db.session.add(sighting)
        db.session.commit()
        
        return jsonify({
            'message': 'Sighting report created successfully',
            'id': sighting.id
        }), 201
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# File Upload Routes
@app.route('/api/upload', methods=['POST'])
def upload_file():
    try:
        if 'file' not in request.files:
            return jsonify({'error': 'No file provided'}), 400
        
        file = request.files['file']
        if file.filename == '':
            return jsonify({'error': 'No file selected'}), 400
        
        filename = save_uploaded_file(file)
        if filename:
            filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            resize_image(filepath)  # Optimize image size
            
            return jsonify({
                'message': 'File uploaded successfully',
                'filename': filename,
                'url': f'/api/uploads/{filename}'
            }), 200
        
        return jsonify({'error': 'Invalid file type'}), 400
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/uploads/<filename>')
def uploaded_file(filename):
    from flask import send_from_directory
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)

# Bird Species Routes
@app.route('/api/species', methods=['GET'])
def get_species():
    try:
        species = BirdSpecies.query.all()
        species_list = [
            {
                'id': s.id,
                'name_th': s.name_th,
                'name_en': s.name_en,
                'description': s.description,
                'characteristics': json.loads(s.characteristics) if s.characteristics else {}
            }
            for s in species
        ]
        
        return jsonify(species_list), 200
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# Statistics Routes
@app.route('/api/stats', methods=['GET'])
def get_statistics():
    try:
        total_lost = LostBird.query.count()
        total_found = FoundBird.query.count()
        total_reunited = LostBird.query.filter_by(status='reunited').count()
        total_sightings = SightingReport.query.count()
        
        # Recent activity
        recent_lost = LostBird.query.filter(
            LostBird.created_at >= datetime.utcnow() - timedelta(days=30)
        ).count()
        
        recent_found = FoundBird.query.filter(
            FoundBird.created_at >= datetime.utcnow() - timedelta(days=30)
        ).count()
        
        return jsonify({
            'total_lost': total_lost,
            'total_found': total_found,
            'total_reunited': total_reunited,
            'total_sightings': total_sightings,
            'recent_lost': recent_lost,
            'recent_found': recent_found,
            'success_rate': round((total_reunited / max(total_lost, 1)) * 100, 2)
        }), 200
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# Database initialization
def init_db():
    """Initialize database and create sample data"""
    db.create_all()
    
    # Create sample bird species
    if not BirdSpecies.query.first():
        sample_species = [
            {
                'name_th': 'นกแก้วโฟรพัส',
                'name_en': 'Rose-ringed Parakeet',
                'description': 'นกแก้วขนาดกลาง สีเขียว มีแถบสีชมพูรอบคอ',
                'characteristics': json.dumps({
                    'size': 'medium',
                    'colors': ['green', 'pink', 'black'],
                    'habitat': 'urban, gardens'
                })
            },
            {
                'name_th': 'นกกรงหัวจุก',
                'name_en': 'Red-whiskered Bulbul',
                'description': 'นกขนาดเล็ก มีหงอกสีดำ แก้มสีแดง',
                'characteristics': json.dumps({
                    'size': 'small',
                    'colors': ['brown', 'white', 'red', 'black'],
                    'habitat': 'gardens, parks'
                })
            },
            {
                'name_th': 'นกขุนทอง',
                'name_en': 'Oriental Magpie-Robin',
                'description': 'นกสีดำขาว ร้องเพลงไพเราะ',
                'characteristics': json.dumps({
                    'size': 'small',
                    'colors': ['black', 'white'],
                    'habitat': 'gardens, urban areas'
                })
            }
        ]
        
        for species_data in sample_species:
            species = BirdSpecies(**species_data)
            db.session.add(species)
        
        db.session.commit()
        print("Sample bird species created!")

if __name__ == '__main__':
    with app.app_context():
        init_db()
    
    app.run(debug=True, host='0.0.0.0', port=5000)