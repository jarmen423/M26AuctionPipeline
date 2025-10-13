import os

# Get the directory where the script is located
script_dir = os.path.dirname(os.path.abspath(__file__))

file_name = 'fresh_capture'
file_path = os.path.join(script_dir, file_name)
# Verify the path to be used (optional but helpful for debugging)
print(f"Target file path: {file_path}")


def clear_file_content(file_name):
    if os.path.exists(file_path):
        with open(file_name, "w") as f:
            f.truncate(0) # Explicitly clears the file
        print(f"Content of {file_name} has been deleted.")
    else:
        print(f"Error: File '{file_name}' not found at {file_path}")

clear_file_content(file_path)