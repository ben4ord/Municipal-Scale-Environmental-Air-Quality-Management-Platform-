from flask import Flask, render_template
from flask_login import LoginManager, login_user, login_required, logout_user, UserMixin, current_user
from flask_sqlalchemy import SQLAlchemy
from flask import Flask, render_template, request, redirect, jsonify
import json
import os
from werkzeug.security import generate_password_hash, check_password_hash



app = Flask(__name__, static_url_path='/static')

app.config["SECRET_KEY"] = os.environ.get(
    "SECRET_KEY",
    "dev-secret-key-change-before-deploying"
)
app.config["SQLALCHEMY_DATABASE_URI"] = "postgresql://postgres:####@localhost:5432/airpollution"

app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
db = SQLAlchemy(app)

# Make sure only users with account can login
login_manager = LoginManager()
login_manager.init_app(app)


# Create user for database 
class User(UserMixin, db.Model):
    __tablename__ = "users"

    user_id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(55), nullable=False, unique=True)
    password_hash = db.Column(db.Text, nullable=False)
    
    # get id
    @property
    def id(self):
        return str(self.user_id)

    # Optional original owner; device access is controlled by user_device.
    owned_devices = db.relationship(
        "Device",
        back_populates="user"
    )

    # get relation to device connection
    device_connections = db.relationship(
        "UserDevice",
        back_populates="user",
        cascade="all, delete"
    )

# Device class
class Device(db.Model):
    __tablename__ = "device"

    device_id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(
        db.Integer,
        db.ForeignKey("users.user_id", ondelete="SET NULL"),
        nullable=True
    )
    device_code = db.Column(db.String(55), nullable=False, unique=True)

    # Devices can start unclaimed; users connect through user_device.
    user = db.relationship("User", back_populates="owned_devices")
    user_connections = db.relationship(
        "UserDevice",
        back_populates="device",
        cascade="all, delete"
    )
    sensors = db.relationship(
        "Sensor",
        back_populates="device",
        cascade="all, delete"
    )


# User device connection
class UserDevice(db.Model):
    __tablename__ = "user_device"

    user_id = db.Column(
        db.Integer,
        db.ForeignKey("users.user_id", ondelete="CASCADE"),
        primary_key=True
    )
    device_id = db.Column(
        db.Integer,
        db.ForeignKey("device.device_id", ondelete="CASCADE"),
        primary_key=True
    )

    user = db.relationship("User", back_populates="device_connections")
    device = db.relationship("Device", back_populates="user_connections")

# Sensor class
class Sensor(db.Model):
    __tablename__ = "sensor"

    sensor_id = db.Column(db.Integer, primary_key=True)
    device_id = db.Column(
        db.Integer,
        db.ForeignKey("device.device_id", ondelete="CASCADE"),
        nullable=False
    )
    name = db.Column(db.String(55), nullable=False)
    type = db.Column(db.String(55), nullable=False)

    device = db.relationship("Device", back_populates="sensors")
    readings = db.relationship(
        "SensorReading",
        back_populates="sensor",
        cascade="all, delete"
    )

# Stores all of the sensor readings
class SensorReading(db.Model):
    __tablename__ = "sensor_reading"

    reading_id = db.Column(db.Integer, primary_key=True)
    sensor_id = db.Column(
        db.Integer,
        db.ForeignKey("sensor.sensor_id", ondelete="CASCADE"),
        nullable=False
    )
    reading_time = db.Column(
        db.DateTime,
        server_default=db.func.current_timestamp(),
        nullable=False
    )
    reading_value = db.Column(db.Float, nullable=False)

    sensor = db.relationship("Sensor", back_populates="readings")


# Collect all of the users connected devices
def get_current_user_devices():
    return (
        db.session.query(Device)
        .join(UserDevice, UserDevice.device_id == Device.device_id)
        .filter(UserDevice.user_id == current_user.user_id)
        .order_by(Device.device_code)
        .all()
    )


# User login and check hashed password
@app.route('/login', methods=['GET', 'POST'])
def login():

    if request.method == 'POST':
        user = User.query.filter_by(
            username=request.form['username']
        ).first()

        if user and check_password_hash(
            user.password_hash,
            request.form['password']
        ):
            # Once user has logged in send them to the sensor data
            login_user(user)
            return redirect('/sensorData')

        return render_template("login.html", error="Invalid username or password")

    return render_template('login.html')

# Create new user
@app.route('/create', methods = ['GET','POST'])
def create():
    userExists = True

    if request.method == 'GET':
        return render_template('create.html')
    elif request.method == 'POST':

        username = request.form['username']
        password = request.form['password']
        hashed = generate_password_hash(password)

        user = User.query.filter_by(username=username).first()
        print(user)

        if user is None:

            user = User(username=username, password_hash=hashed)
            db.session.add(user)
            db.session.commit()
            login_user(user)
            return redirect('/sensorData')
        else:

            return render_template('create.html', userExists=userExists)


# Adding device to a user so they can view their device data
@app.route('/add_device', methods=['GET', 'POST'])
@login_required
def add_device():

    if request.method == 'GET':
        return redirect('/sensorData')

    elif request.method == 'POST':
        device_code = request.form['device_code']
        wants_json = request.headers.get("Accept") == "application/json"

        # Check for existing device
        existing_device = Device.query.filter_by(device_code=device_code).first()
        if existing_device is None:
            if wants_json:
                return jsonify({
                    "success": False,
                    "message": "Device code not found."
                }), 404

            return render_template(
                'sensorData.html',
                devices=get_current_user_devices(),
                error="Device code not found."
            )

        # See if the user has the device already 
        existing_connection = UserDevice.query.filter_by(
            user_id=current_user.user_id,
            device_id=existing_device.device_id
        ).first()

        if existing_connection:
            if wants_json:
                return jsonify({
                    "success": True,
                    "message": "Device already connected.",
                    "device": {
                        "device_id": existing_device.device_id,
                        "device_code": existing_device.device_code
                    }
                })

            return render_template(
                'sensorData.html',
                devices=get_current_user_devices(),
                message="Device already connected."
            )

        new_connection = UserDevice(
            user_id=current_user.user_id,
            device_id=existing_device.device_id
        )

        db.session.add(new_connection)
        db.session.commit()

        if wants_json:
            return jsonify({
                "success": True,
                "message": "Device connected.",
                "device": {
                    "device_id": existing_device.device_id,
                    "device_code": existing_device.device_code
                }
            })

        return render_template(
            'sensorData.html',
            devices=get_current_user_devices(),
            message="Device connected."
        )

@login_manager.user_loader
def load_user(uid):
    return User.query.get(int(uid))

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect('/')

@app.errorhandler(404)
def error(err):

    return render_template("error.html")

@app.errorhandler(401)
def unauthorized(err):

    return render_template("unauthorized.html")

# Homepage route
@app.route("/")
def home():
    if current_user.is_authenticated:
        return redirect('/sensorData')

    return render_template("login.html")


@app.route("/sensorData")
@login_required
def sensor_data():
    return render_template(
        "sensorData.html",
        devices=get_current_user_devices()
    )



@app.route("/api/data")
@login_required
def api_data():
    device_id = request.args.get("device_id", type=int)

    query = (
        db.session.query(
            Sensor.type,
            SensorReading.reading_value,
            SensorReading.reading_time
        )
        .select_from(SensorReading)
        .join(Sensor, SensorReading.sensor_id == Sensor.sensor_id)
        .join(Device, Sensor.device_id == Device.device_id)
        .join(UserDevice, UserDevice.device_id == Device.device_id)
        .filter(UserDevice.user_id == current_user.user_id)
    )

    if device_id is not None:
        query = query.filter(Device.device_id == device_id)

    rows = (
        query
        .order_by(SensorReading.reading_time.desc())
        .limit(500)
        .all()
    )

    rows = list(rows)
    rows.reverse()

    sensor_data = {}

    for s_type, value, timestamp in rows:
        if s_type not in sensor_data:
            sensor_data[s_type] = {
                "labels": [],
                "values": []
            }

        sensor_data[s_type]["labels"].append(
            timestamp.strftime("%Y-%m-%d %H:%M:%S")
        )
        sensor_data[s_type]["values"].append(float(value))

    return sensor_data


if __name__ == "__main__":
    app.run(debug=True)
