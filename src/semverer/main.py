
import ast
import os
import semver
import toml
import base64
import json
import difflib
from typing import Dict, List


class ASTVersionInspector:
    def __init__(self, package_path: str, pyproject_file: str = "pyproject.toml", dry_run: bool = False):
        self.package_path = os.path.abspath(package_path)
        self.pyproject_file = os.path.join(os.path.dirname(self.package_path), pyproject_file)
        self.current_version = self.load_version()
        self.api_signatures = self.load_api_signatures()
        self.dry_run = dry_run


    def load_version(self) -> str:
        """Loads the current semantic version from pyproject.toml."""
        if os.path.exists(self.pyproject_file):
            with open(self.pyproject_file, "r") as f:
                data = toml.load(f)
                return data.get("project", {}).get("version", "0.1.0")
        return "0.1.0"

    def save_version(self, new_version: str, changes: List[str]):
        """Updates the semantic version in pyproject.toml."""
        if self.dry_run:
            print(f"[Dry Run] Would update pyproject.toml to version {new_version}")
            print("[Dry Run] Changes detected:")
            for change in changes:
                print(f"- {change}")
            return

        if os.path.exists(self.pyproject_file):
            with open(self.pyproject_file, "r") as f:
                data = toml.load(f)
            
            if "project" in data:
                data["project"]["version"] = new_version
                data["tool"] = data.get("tool", {})
                data["tool"]["ast_inspector"] = {
                    "api_signatures": base64.b64encode(json.dumps(self.api_signatures).encode()).decode(),
                    "last_changes": changes
                }
                with open(self.pyproject_file, "w") as f:
                    toml.dump(data, f)
                print(f"Updated pyproject.toml to version {new_version}")
                print("Changes detected:")
                for change in changes:
                    print(f"- {change}")

    def load_api_signatures(self) -> Dict[str, Dict]:
        """Loads the stored API signatures from pyproject.toml."""
        if os.path.exists(self.pyproject_file):
            with open(self.pyproject_file, "r") as f:
                data = toml.load(f)
                encoded_signatures = data.get("tool", {}).get("ast_inspector", {}).get("api_signatures", "")
                if encoded_signatures:
                    return json.loads(base64.b64decode(encoded_signatures).decode())
        return {}

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
    
    def generate_diff(self, old: dict, new: dict) -> str:
        """Generates a diff between two versions of a signature."""
        print(type(old))
        print(type(new))
        old_lines = list(old.values())
        new_lines = list(new.values())
        diff = list(difflib.unified_diff(old_lines, new_lines, lineterm=""))
        return "\n".join(diff)
    
    def detect_changes(self, old_signatures: Dict[str, Dict], new_signatures: Dict[str, Dict]) -> (str, List[str]):
        """Detects changes and determines the required version increment."""
        major, minor, patch = 0, 0, 0
        changes = []
        
        for file, new_api in new_signatures.items():
            old_api = old_signatures.get(file, {})
            
            for key in new_api:
                if key not in old_api:
                    minor += 1  # New function or class added
                    changes.append(f"Added {key} in {file}")
                elif new_api[key] != old_api[key]:
                    major += 1  # Breaking change
                    # diff = self.generate_diff(old_api[key], new_api[key])
                    changes.append(f"Changed signature of {key} in {file}:\n")
            
            for key in old_api:
                if key not in new_api:
                    major += 1  # Removed function or class
                    changes.append(f"Removed {key} from {file}")
        
        return self.increment_version(major, minor, patch), changes

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
        """Runs the version analysis and updates pyproject.toml."""
        old_api = self.api_signatures.copy()
        self.scan_package()
        
        if old_api != self.api_signatures:
            new_version, changes = self.detect_changes(old_api, self.api_signatures)
            print(f"Updating version: {self.current_version} -> {new_version}")
            self.save_version(new_version, changes)
        else:
            print("No changes detected in the public API.")
