from flask import Flask, flash, redirect, render_template, request, jsonify, send_file, send_from_directory, url_for, make_response
from pymongo import MongoClient
from gridfs import GridFS
import requests
from werkzeug.utils import secure_filename
import os
import time
import secrets
import string
import random
import qrcode
import qrcode.image.svg
import tempfile


# Generate a random string of characters for the secret key
def generate_secret_key(length=24):
    characters = string.ascii_letters + string.digits + string.punctuation
    return ''.join(secrets.choice(characters) for _ in range(length))


app = Flask(__name__)
# Use the generated key as your secret_key
app.secret_key = generate_secret_key()

# MongoDB configuration
client = MongoClient('mongodb://localhost:27017/')  # Replace with your MongoDB connection URL
db = client['tickets']
fs = GridFS(db)
collection = db['tickets']


# Set the upload folder and allowed extensions
app.config["UPLOAD_FOLDER"] = "uploads"
app.config["ALLOWED_EXTENSIONS"] = {"pdf", "jpeg", "jpg", "png"}
app.config['UPLOAD_FOLDER'] = 'qr_codes'
app.config['MAILGUN_API_KEY'] = '6edd3d20c8bd3a86b64e6dc6bfce6c91-4b98b89f-0f68664a'
app.config['MAILGUN_DOMAIN'] = 'sandboxc833267142b3430d9467639938a14ec4.mailgun.org'

# Limit file size to 1 MB
app.config["MAX_CONTENT_LENGTH"] = 1 * 1024 * 1024  # 1 MB

# Function to check if the file extension is allowed
def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in app.config["ALLOWED_EXTENSIONS"]


@app.route('/')
def index():
    return render_template('index.html')


@app.route("/add_ticket", methods=['GET', 'POST'])
def add_ticket():
    if request.method == "POST":
        traveler_name = request.form["traveler_name"]
        ticket_date = request.form["ticket_date"]
        departure_time = request.form["departure_time"]
        source_city = request.form["source_city"]
        destination_city = request.form["destination_city"]
        mode_of_travel = request.form["mode_of_travel"]
        ticket_file = request.files["ticket_file"]

        # Retrieve the user's email from the form
        user_email = request.form["user_email"]
        
        # Check if the file is allowed and not empty
        if ticket_file and allowed_file(ticket_file.filename):
            # Generate a unique ID for the document
            timestamp = int(time.time() * 1000)  # Convert to milliseconds
            unique_id = f"{timestamp}{random.randint(0, 9999)}"

            # Get the original file extension
            file_extension = ticket_file.filename.rsplit('.', 1)[1].lower() if '.' in ticket_file.filename else ''

            # Create a new filename using the unique ID and original file extension
            new_filename = f"{unique_id}.{file_extension}"

            # Save the file with the new filename in the upload folder
            filename = os.path.join(app.config["UPLOAD_FOLDER"], new_filename)
            ticket_file.save(filename)

            # Create a document to insert into MongoDB
            ticket_data = {
                "unique_id": unique_id,
                "traveler_name": traveler_name,
                "ticket_date": ticket_date,
                "departure_time": departure_time,
                "source_city": source_city,
                "destination_city": destination_city,
                "mode_of_travel": mode_of_travel,
                "ticket_file_path": filename,
            }

            # Insert the document into the MongoDB collection
            collection.insert_one(ticket_data)

            flash("Ticket added successfully.", "success")
            # Retrieve ticket details from the database based on the unique ID
            ticket_details = collection.find_one({"unique_id": unique_id})

            if ticket_details:
                # Redirect the user to the download link
                download_link = url_for('download_ticket_file', unique_id=unique_id, _external=True)

                # Send an email with the download link and ticket details
                email_sent = send_email_with_download_link(user_email, download_link, unique_id, ticket_details)

            if email_sent:
                flash("Ticket added successfully. An email with the download link has been sent to your email address.", "success")
            else:
                flash("Ticket added successfully, but there was an issue sending the email.", "warning")

            # Redirect the user to the same page to clear the form
            return redirect(url_for("add_ticket"))

    return render_template('add_ticket.html')


def send_email_with_download_link(email, download_link, unique_id, ticket_details):
    api_key = app.config['MAILGUN_API_KEY']
    domain = app.config['MAILGUN_DOMAIN']
    subject = 'Your Ticket Details!'

    # Mailgun API endpoint for sending emails
    api_url = f'https://api.mailgun.net/v3/{domain}/messages'

    # Email content
    data = {
        'from': 'khushal sarode <khushalsarode.in@gmail.com>',
        'to': email,
        'subject': subject,
        'html': f'''
            <p>Dear recipient,</p>
            <p>Here are your ticket details:</p>
            <ul>
                <li>Unique ID: {unique_id}</li>
                <li>Traveler Name: {ticket_details['traveler_name']}</li>
                <li>Ticket Date: {ticket_details['ticket_date']}</li>
                <li>Departure Time: {ticket_details['departure_time']}</li>
                <li>Source City: {ticket_details['source_city']}</li>
                <li>Destination City: {ticket_details['destination_city']}</li>
                <li>Mode of Travel: {ticket_details['mode_of_travel']}</li>
            </ul>
            <p>Click the link below to download your ticket:</p>
            <p><a href="{download_link}">Download Ticket</a></p>
        ''',
    }

    # Send the email using the Mailgun API
    response = requests.post(api_url, auth=('api', api_key), data=data)

    # Check if the email was sent successfully
    if response.status_code == 200:
        return True
    else:
        return False

@app.route('/download_ticket/<unique_id>')
def download_ticket_file(unique_id):
    # Retrieve the file path from the MongoDB database based on the unique ID
    file_data = collection.find_one({"unique_id": unique_id})

    if file_data:
        file_path = file_data.get("ticket_file_path")
        
        # Split the file path to get the filename
        filename = os.path.basename(file_path)

        # Send the file as a response for the user to download
        return send_from_directory(app.config['UPLOAD_FOLDER'], filename, as_attachment=True)

    # If the file is not found, return a 404 error
    return "File not found", 404

@app.route("/delete_ticket", methods=['GET','POST'])
def delete_ticket():
    if request.method == "POST":
        ticket_id = request.form["ticket_id"]
        
        # Find the ticket by its unique_id and delete it
        ticket = collection.find_one({"unique_id": ticket_id})
        if ticket:
            # Delete the file associated with the ticket
            file_path = ticket["ticket_file_path"]
            if os.path.exists(file_path):
                os.remove(file_path)
            
            # Delete the ticket document from MongoDB
            collection.delete_one({"unique_id": ticket_id})

            flash("Ticket deleted successfully.", "success")
        else:
            flash("Ticket not found.", "error")

    return render_template('delete.html')

@app.route("/show_ticket", methods=["GET", "POST"])
def show_ticket():
    if request.method == "POST":
        ticket_id = request.form["ticket_id"]
        
        # Query the database to find the ticket
        ticket = collection.find_one({"unique_id": ticket_id})

        if ticket:
            return render_template("show_ticket.html", ticket=ticket)
        else:
            return render_template("show_ticket.html", ticket=None)

    return render_template("show_ticket.html")





'''@app.route('/download_ticket/<unique_id>', methods=['GET', 'POST'])
def download_ticket(unique_id):
    # Fetch the file path from the MongoDB database based on the unique_id
    file_data = collection.find_one({"unique_id": unique_id})

    if file_data:
        file_path = file_data.get("ticket_file_path")

        # Create the full path to the file in your project folder
        full_file_path = os.path.join(app.config['UPLOAD_FOLDER'], file_path)

        # Check if the file exists
        if os.path.exists(full_file_path):
            # Determine the file type based on its extension
            file_extension = os.path.splitext(file_path)[1].lower()

            # Map file extensions to MIME types for proper response headers
            mime_types = {
                '.jpg': 'image/jpeg',
                '.jpeg': 'image/jpeg',
                '.png': 'image/png',
                '.pdf': 'application/pdf',
            }

            # Set the appropriate Content-Type header
            response_headers = {
                'Content-Type': mime_types.get(file_extension, 'application/octet-stream')
            }

            # Send the file as a response
            return send_file(full_file_path, as_attachment=True, attachment_filename=os.path.basename(file_path), headers=response_headers)

    # If the file is not found, return a 404 error
    return "File not found", 404
'''


@app.route('/verify_location', methods=['GET', 'POST'])
def location():
    # Replace with your TomTom API key
    api_key = 'x4FADiYE9RJ6GUihpu9izoW3c23ovweX'
    api_url = 'https://api.tomtom.com/search/2/structuredGeocode.json'

    if request.method == 'POST':
        countryname = request.form['countryname']
        statename = request.form['statename']
        cityname = request.form['cityname']
        street_number = request.form.get('street_number')  # Use request.form.get to make it optional
        street_name = request.form.get('street_name')  # Use request.form.get to make it optional
        cross_street = request.form.get('cross_street')  # Use request.form.get to make it optional
        Areaname = request.form['Areaname']
        postal_code = request.form['postal_code']

        if not countryname or not statename or not cityname:
            result = "Please provide all required information."
        else:
            params = {
                'country': countryname,
                'limit': 1,
                'countrySubdivision': statename,
                'countrySecondarySubdivision': cityname,
                'postalCode':postal_code,
                'municipalitySubdivision':Areaname,
                'key': api_key,
            }

            if street_number:
                params['streetNumber'] = street_number
            if street_name:
                params['streetName'] = street_name
            if cross_street:
                params['crossStreet'] = cross_street
           
            try:
                response = requests.get(api_url, params=params)

                if response.status_code == 200:
                    result = "Location is valid."
                else:
                    result = "Location does not exist."

            except requests.RequestException as e:
                result = "Request error: " + str(e)

        return render_template('verify_location.html', result=result)

    return render_template('verify_location.html', result=None)



def generate_qr_code(unique_id):
    url = f"https://yourwebapp.com/show_ticket?unique_id={unique_id}"
    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_L,
        box_size=10,
        border=4,
    )
    qr.add_data(url)
    qr.make(fit=True)

    # Create a QR code image
    qr_img = qr.make_image(fill_color="black", back_color="white")

    # Define the file extension for the QR code image (e.g., '.png')
    file_extension = '.png'

    # Create a temporary file with the specified file extension
    tmp_file = tempfile.NamedTemporaryFile(suffix=file_extension, delete=False)

    # Save the QR code image to the temporary file
    qr_img.save(tmp_file.name)

    return tmp_file.name

# Function to send an email with a QR code attachment using Mailgun
def send_email_with_qr_code(email, qr_code_path):
    api_key = app.config['MAILGUN_API_KEY']
    domain = app.config['MAILGUN_DOMAIN']

    # Mailgun API endpoint for sending emails
    api_url = f'https://api.mailgun.net/v3/{domain}/messages'

    try:
        # Create a dictionary with email data
        data = {
            'from': 'your_email@example.com',
            'to': email,
            'subject': 'QR Code for Ticket',
            'text': 'Please find the QR code for your ticket attached below.'
        }

        # Attach the QR code file
        with open(qr_code_path, 'rb') as qr_file:
            response = requests.post(
                api_url,
                auth=('api', api_key),
                files=[('attachment', ('qr_code.png', qr_file.read()))],
                data=data
            )

        # Check if the email was sent successfully
        if response.status_code == 200:
            return True
        else:
            print(f"Error sending email: {response.text}")
            return False

    except Exception as e:
        print(f"Error sending email: {str(e)}")
        return False

@app.route('/scan_qr_code', methods=['GET', 'POST'])
def scan_qr_code():
    if request.method == 'POST':
        unique_id = request.form.get('unique_id')
        user_email = request.form.get('user_email')

        if unique_id and user_email:
            # Generate QR code for email
            qr_code_path = generate_qr_code(unique_id)
            
            # Send the QR code via email
            email_sent = send_email_with_qr_code(user_email, qr_code_path)
            
            if email_sent:
                flash("QR code sent to your email.", "success")
            else:
                flash("Failed to send QR code via email.", "danger")
        
        elif unique_id:
            # Generate QR code for download
            qr_code_path = generate_qr_code(unique_id)
            
            # Send the QR code for download
            return send_from_directory(os.path.dirname(qr_code_path), os.path.basename(qr_code_path), as_attachment=True)

    return render_template('scan_qr_code.html')


if __name__ == '__main__':
    app.run(debug=True)

