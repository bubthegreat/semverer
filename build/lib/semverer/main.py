import ast
import os
import semver
from typing import Dict


class ASTVersionInspector:
    def __init__(self, package_path: str, version_file: str = "VERSION"):
        self.package_path = package_path
        self.version_file = os.path.join(package_path, version_file)
        self.current_version = self.load_version()
        self.api_signatures = {}

    def load_version(self) -> str:
        """Loads the current semantic version from the version file."""
        if os.path.exists(self.version_file):
            with open(self.version_file, "r") as f:
                return f.read().strip()
        return "0.1.0"

    def save_version(self, new_version: str):
        """Saves the new semantic version to the version file."""
        with open(self.version_file, "w") as f:
            f.write(new_version)

    def extract_api(self, file_path: str):
        """Extracts the public API signatures from a Python file."""
        with open(file_path, "r", encoding="utf-8") as f:
            tree = ast.parse(f.read(), filename=file_path)
        
        api_elements = {}
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef):
                api_elements[node.name] = self.get_function_signature(node)
            elif isinstance(node, ast.ClassDef):
                api_elements[node.name] = self.get_class_signature(node)
        
        return api_elements
    
    def get_function_signature(self, node: ast.FunctionDef) -> str:
        """Returns a string signature of a function."""
        args = [arg.arg for arg in node.args.args]
        return f"def {node.name}({', '.join(args)})"
    
    def get_class_signature(self, node: ast.ClassDef) -> Dict[str, str]:
        """Returns a dictionary of method signatures for a class."""
        methods = {}
        for child in node.body:
            if isinstance(child, ast.FunctionDef):
                methods[child.name] = self.get_function_signature(child)
        return methods

    def scan_package(self):
        """Scans the package directory and extracts API signatures."""
        for root, _, files in os.walk(self.package_path):
            for file in files:
                if file.endswith(".py") and not file.startswith("_"):
                    file_path = os.path.join(root, file)
                    self.api_signatures[file_path] = self.extract_api(file_path)
    
    def detect_changes(self, old_signatures: Dict[str, Dict], new_signatures: Dict[str, Dict]) -> str:
        """Detects changes and determines the required version increment."""
        major, minor, patch = 0, 0, 0
        
        for file, new_api in new_signatures.items():
            old_api = old_signatures.get(file, {})
            
            for key in new_api:
                if key not in old_api:
                    minor += 1  # New function or class added
                elif new_api[key] != old_api[key]:
                    major += 1  # Breaking change
            
            for key in old_api:
                if key not in new_api:
                    major += 1  # Removed function or class
        
        return self.increment_version(major, minor, patch)
    
    def increment_version(self, major: int, minor: int, patch: int) -> str:
        """Increments the version based on detected changes."""
        version = semver.Version.parse(self.current_version)
        if major:
            version = version.bump_major()
        elif minor:
            version = version.bump_minor()
        elif patch:
            version = version.bump_patch()
        return str(version)

    def run(self):
        """Runs the version analysis and updates the version file."""
        old_api = self.api_signatures.copy()
        self.scan_package()
        new_version = self.detect_changes(old_api, self.api_signatures)
        
        if new_version != self.current_version:
            print(f"Updating version: {self.current_version} -> {new_version}")
            self.save_version(new_version)
        else:
            print("No changes detected in the public API.")
