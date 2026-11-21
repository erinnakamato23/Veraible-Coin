import hashlib
import hmac
import base64
import json
import os
import sys
import math
import random
import shutil
import subprocess
import tempfile
import urllib.request
import urllib.error
from time import time, sleep
from flask import Flask, jsonify, request, render_template, send_file
import ecdsa
import threading
import secrets
import socket
import uuid

try:
    import webview
except ImportError:
    webview = None

try:
    import miniupnpc
except ImportError:
    miniupnpc = None

# =====================================================================
# GLOBAL CONFIGURATION, VERSIONING, DOMAIN ROUTING & STORAGE PATHS
# =====================================================================
APP_VERSION = "1.0.0"
MIN_SUPPORTED_VERSION = "1.0.0"

# Run with VCP_SERVER_MODE=web on the public server; default is "desktop".
SERVER_MODE = os.getenv("VCP_SERVER_MODE", "desktop").strip().lower()
if SERVER_MODE not in ("web", "desktop"):
    SERVER_MODE = "desktop"

PRIMARY_DOMAIN = os.getenv("VCP_PRIMARY_DOMAIN", "https://veriable2.org").rstrip("/")

if sys.platform == "win32":
    BASE_STORAGE_DIR = os.path.join(os.getenv("APPDATA", os.path.expanduser("~")), "VariableCoin")
else:
    BASE_STORAGE_DIR = os.path.abspath(os.path.dirname(__file__))

os.makedirs(BASE_STORAGE_DIR, exist_ok=True)

BLOCKS_STORAGE_DIR = os.path.join(BASE_STORAGE_DIR, "variable_blocks")
KNOWN_PEERS_FILE = os.path.join(BASE_STORAGE_DIR, "known_peers.json")
PROTOCOL_STATE_FILE = os.path.join(BASE_STORAGE_DIR, "protocol_state.json")
NODE_IDENTITY_FILE = os.path.join(BASE_STORAGE_DIR, "node_identity.json")
PENDING_REQUESTS_FILE = os.path.join(BASE_STORAGE_DIR, "pending_requests.json")

# Downloadable release artifacts served by the web portal
SCRIPT_DIR = os.path.abspath(os.path.dirname(__file__))
DESKTOP_ZIP_PATH = os.getenv("VCP_DESKTOP_ZIP", os.path.join(SCRIPT_DIR, "VariableCoin_Desktop.zip"))
DESKTOP_EXE_PATH = os.getenv("VCP_DESKTOP_EXE", os.path.join(SCRIPT_DIR, "VariableCoin.exe"))

DEFAULT_TCP_PORT = 6000
DEFAULT_UDP_PORT = 6001
DEFAULT_HTTP_PORT = int(os.getenv("VCP_HTTP_PORT", "5000"))

PEER_RELAY_URLS = [
    PRIMARY_DOMAIN
]

HEARTBEAT_INTERVAL_SEC = 30
NODE_TIMEOUT_SEC = 90
PEER_TIMEOUT_SEC = 5.0
RELAY_SYNC_INTERVAL_SEC = 30

STORAGE_SAFETY_MARGIN_MB = 250
THERMAL_TIME_THRESHOLD = 0.85


# =====================================================================
# VERSION MANAGEMENT & AUTOMATIC SELF-UPDATER (WINDOWS DESKTOP .EXE)
# =====================================================================
class VersionManager:
    """Handles semantic version parsing and protocol compatibility checks."""
    @staticmethod
    def parse_version(version_str):
        try:
            parts = str(version_str).strip().split(".")
            return tuple(int(p) for p in parts[:3])
        except Exception:
            return (0, 0, 0)

    @staticmethod
    def is_version_supported(client_version, min_version=MIN_SUPPORTED_VERSION):
        return VersionManager.parse_version(client_version) >= VersionManager.parse_version(min_version)

    @staticmethod
    def is_update_available(current_version, latest_version):
        return VersionManager.parse_version(latest_version) > VersionManager.parse_version(current_version)


class AutoUpdater:
    """Checks for updates via PRIMARY_DOMAIN and self-replaces frozen Windows binaries."""
    @staticmethod
    def check_and_apply_update():
        if SERVER_MODE == "web":
            return False

        try:
            req = urllib.request.Request(
                f"{PRIMARY_DOMAIN}/api/version",
                headers={"User-Agent": f"VariableCoinNode/{APP_VERSION}"},
                method="GET"
            )
            with urllib.request.urlopen(req, timeout=PEER_TIMEOUT_SEC) as resp:
                info = json.loads(resp.read().decode("utf-8"))
        except Exception:
            return False

        latest_version = str(info.get("latest_version", APP_VERSION)).strip()
        download_url = str(info.get("exe_download_url", f"{PRIMARY_DOMAIN}/download/exe")).strip()

        if not VersionManager.is_update_available(APP_VERSION, latest_version):
            return False

        # Only self-replace when running as a compiled Windows executable
        if not getattr(sys, "frozen", False) or sys.platform != "win32":
            print(f"[UPDATER] New version {latest_version} available at {download_url}")
            return False

        current_exe = os.path.abspath(sys.executable)
        new_exe = os.path.join(tempfile.gettempdir(), f"VariableCoin_{latest_version}.exe")

        try:
            dl_req = urllib.request.Request(
                download_url,
                headers={"User-Agent": f"VariableCoinNode/{APP_VERSION}"},
                method="GET"
            )
            with urllib.request.urlopen(dl_req, timeout=60) as resp, open(new_exe, "wb") as out_file:
                shutil.copyfileobj(resp, out_file)

            if not os.path.exists(new_exe) or os.path.getsize(new_exe) < 1024 * 100:
                return False

            bat_path = os.path.join(tempfile.gettempdir(), "vcp_auto_updater.bat")
            bat_script = (
                "@echo off\n"
                "timeout /t 2 /nobreak >nul\n"
                f'move /y "{new_exe}" "{current_exe}" >nul\n'
                f'start "" "{current_exe}"\n'
                'del "%~f0"\n'
            )
            with open(bat_path, "w", encoding="utf-8") as bf:
                bf.write(bat_script)

            creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
            subprocess.Popen(
                ["cmd.exe", "/c", bat_path],
                creationflags=creation_flags,
                close_fds=True
            )
            os._exit(0)
        except Exception:
            return False


# =====================================================================
# CRYPTOGRAPHIC IP OBFUSCATION & VARIABLE SLOT SECURITY LAYER
# =====================================================================
class IPSecurityLayer:
    """Encrypts peer endpoints ('ip:port') and generates blind fingerprints."""
    NETWORK_SECRET_SALT = os.getenv("VCP_IP_SALT", "VARIABLE_PROTOCOL_256BIT_IP_SHIELD_V1")

    @staticmethod
    def is_valid_host_config(value):
        if not value:
            return False
        clean_val = str(value).strip()
        if "YOUR_DOMAIN_HERE" in clean_val or "YOUR_SERVER_IP_HERE" in clean_val:
            return False
        if clean_val in ("127.0.0.1", "0.0.0.0", "localhost", "NODE"):
            return False
        return True

    @staticmethod
    def _derive_slot_key(variable_slot="GLOBAL_SLOT", epoch=None):
        active_epoch = epoch if epoch is not None else int(time() // 86400)
        seed_material = f"{IPSecurityLayer.NETWORK_SECRET_SALT}:{variable_slot}:{active_epoch}"
        return hashlib.sha256(seed_material.encode("utf-8")).digest()

    @staticmethod
    def _keystream_xor(data_bytes, key_bytes, nonce_bytes):
        output = bytearray(len(data_bytes))
        block_count = (len(data_bytes) + 31) // 32
        for i in range(block_count):
            counter_bytes = i.to_bytes(4, byteorder="big")
            stream_block = hashlib.sha256(key_bytes + nonce_bytes + counter_bytes).digest()
            start = i * 32
            end = min(start + 32, len(data_bytes))
            for j in range(start, end):
                output[j] = data_bytes[j] ^ stream_block[j - start]
        return bytes(output)

    @staticmethod
    def encrypt_endpoint(peer_address, variable_slot="GLOBAL_SLOT", epoch=None):
        if not peer_address or str(peer_address).startswith("ENC_IP_"):
            return peer_address
        key = IPSecurityLayer._derive_slot_key(variable_slot, epoch)
        nonce = secrets.token_bytes(12)
        plaintext = str(peer_address).strip().encode("utf-8")
        ciphertext = IPSecurityLayer._keystream_xor(plaintext, key, nonce)
        mac = hmac.new(key, nonce + ciphertext, hashlib.sha256).digest()[:16]
        token = base64.urlsafe_b64encode(nonce + mac + ciphertext).decode("ascii")
        return f"ENC_IP_{token}"

    @staticmethod
    def decrypt_endpoint(encrypted_token, variable_slot="GLOBAL_SLOT", epoch=None):
        if not encrypted_token:
            return None
        token_str = str(encrypted_token).strip()
        if not token_str.startswith("ENC_IP_"):
            return token_str

        raw_b64 = token_str[7:]
        current_epoch = epoch if epoch is not None else int(time() // 86400)

        for candidate_slot in (variable_slot, "GLOBAL_SLOT"):
            for candidate_epoch in (current_epoch, current_epoch - 1):
                try:
                    raw_bytes = base64.urlsafe_b64decode(raw_b64.encode("ascii"))
                    if len(raw_bytes) <= 28:
                        continue
                    nonce = raw_bytes[:12]
                    mac = raw_bytes[12:28]
                    ciphertext = raw_bytes[28:]

                    key = IPSecurityLayer._derive_slot_key(candidate_slot, candidate_epoch)
                    expected_mac = hmac.new(key, nonce + ciphertext, hashlib.sha256).digest()[:16]
                    if hmac.compare_digest(mac, expected_mac):
                        decrypted = IPSecurityLayer._keystream_xor(ciphertext, key, nonce).decode("utf-8")
                        if ":" in decrypted:
                            return decrypted
                except Exception:
                    continue
        return None

    @staticmethod
    def fingerprint_endpoint(peer_address):
        raw = str(peer_address).strip()
        digest = hashlib.sha256(f"{IPSecurityLayer.NETWORK_SECRET_SALT}:BLIND:{raw}".encode("utf-8")).hexdigest()[:16]
        return f"BLIND_{digest.upper()}"


# =====================================================================
# PERSISTENT NODE IDENTITY & AUTOMATIC UPnP PORT FORWARDING
# =====================================================================
class NodeIdentityAndUPnPManager:
    """Manages persistent Node ID and automatic UPnP port forwarding."""
    @staticmethod
    def get_or_create_node_id():
        if os.path.exists(NODE_IDENTITY_FILE):
            try:
                with open(NODE_IDENTITY_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if data.get("node_id"):
                        return data["node_id"]
            except Exception:
                pass

        hw_mac = hex(uuid.getnode())
        random_salt = secrets.token_hex(8)
        raw_id = hashlib.sha256(f"VARIABLE_NODE_ID_{hw_mac}_{random_salt}".encode("utf-8")).hexdigest()[:24]
        node_id = f"NODE_{raw_id.upper()}"

        try:
            with open(NODE_IDENTITY_FILE, "w", encoding="utf-8") as f:
                json.dump({
                    "node_id": node_id,
                    "created_at": int(time())
                }, f, indent=2)
        except Exception:
            pass

        return node_id

    @staticmethod
    def configure_upnp_ports(tcp_port=DEFAULT_TCP_PORT, udp_port=DEFAULT_UDP_PORT):
        result = {
            "upnp_active": False,
            "encrypted_external_endpoint": None,
            "tcp_port": tcp_port,
            "udp_port": udp_port,
            "status_message": "UPnP module not installed or router does not support UPnP."
        }
        if miniupnpc is None or SERVER_MODE == "web":
            if SERVER_MODE == "web":
                result["status_message"] = "UPnP skipped in web server mode."
            return result

        try:
            upnp = miniupnpc.UPnP()
            upnp.discoverdelay = 200
            devices = upnp.discover()
            if devices > 0:
                upnp.selectigd()
                ext_ip = upnp.externalipaddress()
                local_ip = upnp.lanaddr

                upnp.addportmapping(
                    tcp_port, "TCP", local_ip, tcp_port,
                    "VariableCoin P2P TCP", ""
                )
                upnp.addportmapping(
                    udp_port, "UDP", local_ip, udp_port,
                    "VariableCoin P2P UDP", ""
                )

                encrypted_ext = IPSecurityLayer.encrypt_endpoint(f"{ext_ip}:{tcp_port}", "GLOBAL_SLOT")
                blind_id = IPSecurityLayer.fingerprint_endpoint(f"{ext_ip}:{tcp_port}")

                result["upnp_active"] = True
                result["encrypted_external_endpoint"] = encrypted_ext
                result["blind_endpoint_id"] = blind_id
                result["status_message"] = f"UPnP Port Forwarding Active (Endpoint Shielded: {blind_id})"
        except Exception as e:
            result["status_message"] = f"UPnP fallback mode: {str(e)}"

        return result


# =====================================================================
# 256-BIT CRYPTOGRAPHIC ENGINE (SECP256K1) & TX SIGNATURES
# =====================================================================
def generate_master_wallet():
    """Generates a new SECP256k1 private and public key pair."""
    priv_bytes = secrets.token_bytes(32)
    sk = ecdsa.SigningKey.from_string(priv_bytes, curve=ecdsa.SECP256k1)
    vk = sk.verifying_key
    return {
        "private_key": sk.to_string().hex(),
        "public_key": vk.to_string().hex()
    }


def wallet_from_private_key(private_key_hex):
    """Recovers the public wallet address from an existing 64-character hex private key."""
    clean_hex = str(private_key_hex).strip().lower()
    if len(clean_hex) != 64:
        return None, None, f"Invalid key length ({len(clean_hex)} chars). Must be exactly 64 hex characters."
    try:
        key_int = int(clean_hex, 16)
        curve_order = ecdsa.SECP256k1.order
        if key_int <= 0 or key_int >= curve_order:
            return None, None, "Scalar value is outside SECP256k1 curve boundaries."
        sk = ecdsa.SigningKey.from_string(bytes.fromhex(clean_hex), curve=ecdsa.SECP256k1)
        vk = sk.verifying_key
        return sk.to_string().hex(), vk.to_string().hex(), None
    except ValueError:
        return None, None, "Format error: Private key must contain hexadecimal characters only."
    except Exception as e:
        return None, None, f"Cryptographic validation error: {str(e)}"


def verify_key_match(private_key_hex, public_key_hex):
    """Verifies that a given private key corresponds to the provided public key."""
    if not private_key_hex or not public_key_hex:
        return False
    try:
        clean_hex = str(private_key_hex).strip().lower()
        if len(clean_hex) != 64:
            return False
        sk = ecdsa.SigningKey.from_string(bytes.fromhex(clean_hex), curve=ecdsa.SECP256k1)
        return sk.verifying_key.to_string().hex() == str(public_key_hex).strip().lower()
    except Exception:
        return False


def serialize_transaction_for_signing(tx_data):
    """Produces a deterministic byte payload for ECDSA transaction signing."""
    signable = {k: v for k, v in tx_data.items() if k != "signature"}
    return json.dumps(signable, sort_keys=True, separators=(",", ":")).encode("utf-8")


def sign_transaction(private_key_hex, tx_data):
    """Signs a transaction dictionary using SECP256k1 + SHA-256 and returns hex signature."""
    clean_hex = str(private_key_hex).strip().lower()
    sk = ecdsa.SigningKey.from_string(bytes.fromhex(clean_hex), curve=ecdsa.SECP256k1)
    payload = serialize_transaction_for_signing(tx_data)
    sig_bytes = sk.sign_deterministic(payload, hashfunc=hashlib.sha256)
    return sig_bytes.hex()


def verify_transaction_signature(tx_data):
    """Verifies the ECDSA signature of a non-coinbase transaction."""
    sender = str(tx_data.get("sender", "")).strip().lower()
    if sender == "0":
        return True
    sig_hex = tx_data.get("signature")
    if not sig_hex or len(sender) != 128:
        return False
    try:
        vk = ecdsa.VerifyingKey.from_string(bytes.fromhex(sender), curve=ecdsa.SECP256k1)
        payload = serialize_transaction_for_signing(tx_data)
        return vk.verify(bytes.fromhex(sig_hex), payload, hashfunc=hashlib.sha256)
    except Exception:
        return False


def get_tier_for_power(power):
    """Categorizes Shield token power into standard brackets."""
    p = float(power)
    if p >= 70.0:
        return "tier_99_70"
    elif p >= 50.0:
        return "tier_70_50"
    elif p >= 30.0:
        return "tier_50_30"
    elif p >= 10.0:
        return "tier_30_10"
    elif p >= 1.0:
        return "tier_10_1"
    else:
        return "tier_below_1"


# =====================================================================
# THE 1-99 VARIABLE RULE AND HARDWARE GOVERNOR
# =====================================================================
class VariableRuleGovernor:
    """Implements the 1-99 Variable Rule and hardware safety checks."""
    @staticmethod
    def get_current_epoch():
        return int(time() // 86400)

    @staticmethod
    def get_free_disk_mb():
        try:
            total, used, free = shutil.disk_usage(BASE_STORAGE_DIR)
            return free // (1024 * 1024)
        except Exception:
            return 1000

    @staticmethod
    def check_thermal_pressure(processing_duration):
        return processing_duration > THERMAL_TIME_THRESHOLD

    @staticmethod
    def assign_variable_slot(node_id, epoch):
        seed = f"UNBOUNDED_VARIABLE_SLOT_{node_id}_{epoch}"
        raw_hash = int(hashlib.sha256(seed.encode("utf-8")).hexdigest(), 16)
        return f"VAR_{raw_hash}"

    @staticmethod
    def assign_block_variable_slot(coin_type, index, epoch):
        seed = f"BLOCK_VARIABLE_SLOT_{coin_type}_{index}_{epoch}"
        raw_hash = int(hashlib.sha256(seed.encode("utf-8")).hexdigest(), 16)
        return f"VAR_{raw_hash}"

    @staticmethod
    def assign_node_value_1_99(node_id, epoch):
        seed = f"VARIABLE_RULE_1_99_{node_id}_{epoch}"
        raw_hash = int(hashlib.sha256(seed.encode("utf-8")).hexdigest(), 16)
        return (raw_hash % 99) + 1

    @staticmethod
    def compute_block_requirement_1_99(coin_type, index, epoch, variable_slot):
        seed = f"BLOCK_REQUIREMENT_{coin_type}_{index}_{epoch}_{variable_slot}"
        raw_hash = int(hashlib.sha256(seed.encode("utf-8")).hexdigest(), 16)
        return (raw_hash % 99) + 1

    @staticmethod
    def get_effective_node_value(assigned_value, is_overheating=False):
        free_mb = VariableRuleGovernor.get_free_disk_mb()
        if free_mb < STORAGE_SAFETY_MARGIN_MB:
            return 1
        if is_overheating:
            return max(1, assigned_value // 3)
        if free_mb < STORAGE_SAFETY_MARGIN_MB * 2:
            return max(1, assigned_value // 2)
        return assigned_value


class VariableMiningEngine:
    """Implements the 1-99 Variable Rule for proof-of-work mining."""
    @staticmethod
    def search_variable(seed_identifier, mining_power_1_99, node_variable_slot, node_value_1_99, coin_type="MAIN"):
        if mining_power_1_99 <= 0.0:
            return None, 0, 0.0

        attempts = 0
        max_attempts_per_cycle = 350000 if coin_type == "MAIN" else 500000

        normalized_ratio = max(0.0000001, min(1.0, float(mining_power_1_99) / 99.0))
        acceptance_threshold = 99.0 * (normalized_ratio ** 2.75)

        while attempts < max_attempts_per_cycle:
            attempts += 1
            candidate_seed = f"{seed_identifier}_{node_variable_slot}_{node_value_1_99}_{attempts}"
            candidate_hash = hashlib.sha256(candidate_seed.encode("utf-8")).hexdigest()

            val = int(hashlib.md5(candidate_hash.encode("utf-8")).hexdigest(), 16)
            variable_point = (val % 99000000) / 1000000.0

            if variable_point <= acceptance_threshold:
                return candidate_hash, attempts, round(variable_point, 4)

        return None, attempts, round(acceptance_threshold, 4)


# =====================================================================
# FULL-ARCHIVE & 1-99 ACTIVE/PASSIVE VARIABLE STORAGE ENGINE
# =====================================================================
class VariableStorageEngine:
    """Full-Archive + 1-99 Active/Passive Storage Engine."""
    def __init__(self, base_dir=BLOCKS_STORAGE_DIR):
        self.base_dir = base_dir
        os.makedirs(self.base_dir, exist_ok=True)
        self.memory_blocks = {}
        self.storage_lock = threading.Lock()

    def _get_cluster_id(self, index):
        idx = int(index)
        return ((idx - 1) // 99) + 1

    def _get_cluster_offset(self, index):
        idx = int(index)
        return ((idx - 1) % 99) + 1

    def _block_path(self, coin_type, index):
        cluster_id = self._get_cluster_id(index)
        cluster_folder = os.path.join(self.base_dir, f"cluster_{cluster_id}")
        os.makedirs(cluster_folder, exist_ok=True)
        return os.path.join(cluster_folder, f"{coin_type}_{index}.json")

    def _read_disk_block(self, coin_type, index):
        path = self._block_path(coin_type, index)
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass
        return None

    def _write_disk_block(self, coin_type, index, full_block):
        path = self._block_path(coin_type, index)
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(full_block, f, indent=2)
        except Exception:
            pass

    def _build_memory_projection(self, full_block, node_assigned_value, epoch, variable_slot, is_overheating=False):
        coin_type = full_block.get("coin_type", "MAIN")
        idx = int(full_block["index"])

        block_var_slot = VariableRuleGovernor.assign_block_variable_slot(coin_type, idx, epoch)
        required_value = VariableRuleGovernor.compute_block_requirement_1_99(
            coin_type, idx, epoch, variable_slot
        )
        effective_value = VariableRuleGovernor.get_effective_node_value(
            node_assigned_value, is_overheating
        )

        mem_block = dict(full_block)
        tx_payload = full_block.get("transactions", [])

        mem_block["cluster_id"] = self._get_cluster_id(idx)
        mem_block["cluster_offset"] = self._get_cluster_offset(idx)
        mem_block["assigned_variable_slot"] = variable_slot
        mem_block["block_variable_slot"] = block_var_slot
        mem_block["epoch"] = epoch
        mem_block["required_value_1_99"] = required_value
        mem_block["node_value_1_99"] = effective_value
        mem_block["transaction_count"] = len(tx_payload)

        if effective_value >= required_value:
            mem_block["status"] = "ACTIVE"
            mem_block["transactions"] = list(tx_payload)
        else:
            mem_block["status"] = "PASSIVE"
            mem_block["transactions"] = []

        return mem_block

    def allocate_block(self, block, node_assigned_value=99, epoch=None, variable_slot="VAR_INIT", is_overheating=False):
        with self.storage_lock:
            coin_type = block.get("coin_type", "MAIN")
            idx = int(block["index"])
            current_epoch = epoch if epoch is not None else VariableRuleGovernor.get_current_epoch()

            full_block = dict(block)
            tx_payload = list(full_block.get("transactions", []))

            if not tx_payload:
                existing_disk = self._read_disk_block(coin_type, idx)
                if existing_disk and existing_disk.get("transactions"):
                    tx_payload = existing_disk["transactions"]
                    full_block["transactions"] = tx_payload

            full_block["cluster_id"] = self._get_cluster_id(idx)
            full_block["cluster_offset"] = self._get_cluster_offset(idx)
            full_block["assigned_variable_slot"] = variable_slot
            full_block["block_variable_slot"] = VariableRuleGovernor.assign_block_variable_slot(
                coin_type, idx, current_epoch
            )
            full_block["epoch"] = current_epoch
            full_block["data_snapshot_hash"] = hashlib.sha256(
                json.dumps(tx_payload, sort_keys=True).encode("utf-8")
            ).hexdigest()

            self._write_disk_block(coin_type, idx, full_block)

            mem_block = self._build_memory_projection(
                full_block, node_assigned_value, current_epoch, variable_slot, is_overheating
            )
            self.memory_blocks[(coin_type, idx)] = mem_block

            full_block["required_value_1_99"] = mem_block["required_value_1_99"]
            full_block["node_value_1_99"] = mem_block["node_value_1_99"]
            full_block["status"] = mem_block["status"]
            return full_block

    def rotate_all_blocks_for_new_epoch(self, new_node_value, new_epoch, new_variable_slot, is_overheating=False):
        with self.storage_lock:
            active_count = 0
            passive_count = 0
            for (coin_type, idx) in list(self.memory_blocks.keys()):
                full_disk_block = self._read_disk_block(coin_type, idx)
                if not full_disk_block:
                    full_disk_block = self.memory_blocks[(coin_type, idx)]

                mem_block = self._build_memory_projection(
                    full_disk_block, new_node_value, new_epoch, new_variable_slot, is_overheating
                )
                self.memory_blocks[(coin_type, idx)] = mem_block
                if mem_block["status"] == "ACTIVE":
                    active_count += 1
                else:
                    passive_count += 1

            return {
                "epoch": new_epoch,
                "variable_slot": new_variable_slot,
                "node_value_1_99": new_node_value,
                "active_blocks": active_count,
                "passive_blocks": passive_count
            }

    def get_block(self, coin_type, index, full_data=True):
        idx = int(index)
        mem_block = self.memory_blocks.get((coin_type, idx))

        if not full_data and mem_block is not None:
            return dict(mem_block)

        disk_block = self._read_disk_block(coin_type, idx)
        if disk_block:
            if mem_block:
                disk_block["status"] = mem_block.get("status", "ACTIVE")
                disk_block["required_value_1_99"] = mem_block.get("required_value_1_99", 1)
                disk_block["node_value_1_99"] = mem_block.get("node_value_1_99", 99)
                disk_block["assigned_variable_slot"] = mem_block.get("assigned_variable_slot", "VAR_INIT")
                disk_block["block_variable_slot"] = mem_block.get("block_variable_slot", "VAR_INIT")
                disk_block["epoch"] = mem_block.get("epoch", VariableRuleGovernor.get_current_epoch())
            return disk_block

        return dict(mem_block) if mem_block else None

    def load_all_shards(self, node_assigned_value=99, epoch=None, variable_slot="VAR_INIT", is_overheating=False):
        with self.storage_lock:
            self.memory_blocks.clear()
            if not os.path.exists(self.base_dir):
                return

            current_epoch = epoch if epoch is not None else VariableRuleGovernor.get_current_epoch()

            for folder_name in os.listdir(self.base_dir):
                folder_path = os.path.join(self.base_dir, folder_name)
                if os.path.isdir(folder_path) and folder_name.startswith("cluster_"):
                    for fname in os.listdir(folder_path):
                        if fname.endswith(".json"):
                            parts = fname[:-5].rsplit("_", 1)
                            if len(parts) == 2:
                                coin_type, idx_str = parts
                                try:
                                    idx = int(idx_str)
                                    fpath = os.path.join(folder_path, fname)
                                    with open(fpath, "r", encoding="utf-8") as f:
                                        full_block = json.load(f)
                                        mem_block = self._build_memory_projection(
                                            full_block,
                                            node_assigned_value,
                                            current_epoch,
                                            variable_slot,
                                            is_overheating
                                        )
                                        self.memory_blocks[(coin_type, idx)] = mem_block
                                except Exception:
                                    pass

    def get_chain_length(self, coin_type):
        indices = [k[1] for k in self.memory_blocks.keys() if k[0] == coin_type]
        return max(indices) if indices else 0

    def get_all_blocks(self, coin_type, include_passive_data=True):
        result = {}
        indices = sorted([idx for (c, idx) in self.memory_blocks.keys() if c == coin_type])
        for idx in indices:
            b = self.get_block(coin_type, idx, full_data=include_passive_data)
            if b:
                result[idx] = b
        return result

    def get_storage_metrics(self, coin_type=None):
        total = 0
        active = 0
        passive = 0
        for (c, _), b in self.memory_blocks.items():
            if coin_type is None or c == coin_type:
                total += 1
                if b.get("status") == "ACTIVE":
                    active += 1
                else:
                    passive += 1
        active_pct = round((active / total) * 100.0, 2) if total > 0 else 0.0
        return {
            "total_blocks_on_disk": total,
            "active_blocks_in_memory": active,
            "passive_blocks_on_disk": passive,
            "active_percentage": active_pct
        }

    def activate_all_blocks_on_demand(self, coin_type=None):
        if coin_type:
            return self.get_all_blocks(coin_type, include_passive_data=True)
        return {
            "MAIN": self.get_all_blocks("MAIN", include_passive_data=True),
            "SHIELD_COIN": self.get_all_blocks("SHIELD_COIN", include_passive_data=True)
        }# =====================================================================
# CORE BLOCKCHAIN PROTOCOL ENGINE
# =====================================================================
class Blockchain(object):
    def __init__(self, node_id=None):
        self.current_main_transactions = []
        self.current_alt_transactions = []
        self.BURN_ADDRESS = "0x000000000000000000000000000000000000dEaD"
        self.lock = threading.RLock()

        self.node_id = node_id or NodeIdentityAndUPnPManager.get_or_create_node_id()
        initial_epoch = VariableRuleGovernor.get_current_epoch()
        initial_slot = VariableRuleGovernor.assign_variable_slot(self.node_id, initial_epoch)
        initial_val = VariableRuleGovernor.assign_node_value_1_99(self.node_id, initial_epoch)

        self.storage = VariableStorageEngine()
        self.storage.load_all_shards(
            node_assigned_value=initial_val,
            epoch=initial_epoch,
            variable_slot=initial_slot
        )

        self.BASE_MAX_MAIN = 21000000
        self.BASE_MAIN_REWARD = 50
        self.dynamic_supply_offset = 0
        self.supply_variance_limit = 5000000
        self.burned_main_coins = 0

        self.sub_coin_name = "SHIELD_COIN"
        self.market_boost_bonus = 0.0
        self.market_peg_active = False
        self.user_stats = {}
        self.known_peers = set()

        # Live node registry: node_id -> {"last_seen": ts, "blind_id": str, "encrypted_endpoint": str, "version": str}
        self.active_nodes = {}
        self.nodes_lock = threading.Lock()

        self.load_protocol_state()
        self.load_known_peers()

        if self.storage.get_chain_length("MAIN") == 0:
            self.mint_block(
                proof=1,
                coin_type="MAIN",
                previous_hash="1",
                node_value_1_99=initial_val,
                variable_slot=initial_slot,
                variable_hash="GENESIS_VAR"
            )

        if self.storage.get_chain_length(self.sub_coin_name) == 0:
            self.mint_block(
                proof=1,
                coin_type=self.sub_coin_name,
                previous_hash="1",
                node_value_1_99=initial_val,
                variable_slot=initial_slot,
                variable_hash="GENESIS_VAR"
            )

    def load_known_peers(self):
        if os.path.exists(KNOWN_PEERS_FILE):
            try:
                with open(KNOWN_PEERS_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if isinstance(data, list):
                        for p in data:
                            self.known_peers.add(str(p))
                    elif isinstance(data, dict) and "peers" in data:
                        for p in data["peers"]:
                            self.known_peers.add(str(p))
            except Exception:
                pass

    def register_node_heartbeat(self, node_id, client_ip, encrypted_endpoint=None, client_version=APP_VERSION):
        """Updates or registers a live node by persistent node_id."""
        if not node_id or not str(node_id).startswith("NODE_"):
            return
        now = time()
        blind_id = IPSecurityLayer.fingerprint_endpoint(f"{client_ip}:{DEFAULT_TCP_PORT}")
        enc_ep = encrypted_endpoint or IPSecurityLayer.encrypt_endpoint(f"{client_ip}:{DEFAULT_TCP_PORT}", "GLOBAL_SLOT")
        with self.nodes_lock:
            self.active_nodes[str(node_id)] = {
                "last_seen": now,
                "blind_id": blind_id,
                "encrypted_endpoint": enc_ep,
                "version": str(client_version)
            }

    def prune_stale_nodes(self):
        """Removes nodes that have not sent a heartbeat within NODE_TIMEOUT_SEC."""
        now = time()
        with self.nodes_lock:
            stale_ids = [
                nid for nid, info in self.active_nodes.items()
                if (now - info.get("last_seen", 0)) > NODE_TIMEOUT_SEC
            ]
            for nid in stale_ids:
                del self.active_nodes[nid]

    def get_active_peers_count(self):
        self.prune_stale_nodes()
        with self.nodes_lock:
            live_count = len(self.active_nodes)
        return 1 + live_count

    def get_active_nodes_snapshot(self):
        self.prune_stale_nodes()
        with self.nodes_lock:
            return [
                {
                    "node_id": nid,
                    "blind_id": info.get("blind_id"),
                    "encrypted_endpoint": info.get("encrypted_endpoint"),
                    "version": info.get("version", APP_VERSION),
                    "last_seen": int(info.get("last_seen", 0))
                }
                for nid, info in self.active_nodes.items()
            ]

    def save_protocol_state(self):
        state = {
            "dynamic_supply_offset": self.dynamic_supply_offset,
            "burned_main_coins": self.burned_main_coins,
            "market_boost_bonus": self.market_boost_bonus,
            "market_peg_active": self.market_peg_active,
            "user_stats": self.user_stats
        }
        try:
            with open(PROTOCOL_STATE_FILE, "w", encoding="utf-8") as f:
                json.dump(state, f, indent=2)
        except Exception:
            pass

    def load_protocol_state(self):
        if os.path.exists(PROTOCOL_STATE_FILE):
            try:
                with open(PROTOCOL_STATE_FILE, "r", encoding="utf-8") as f:
                    state = json.load(f)
                    self.dynamic_supply_offset = state.get("dynamic_supply_offset", 0)
                    self.burned_main_coins = state.get("burned_main_coins", 0)
                    self.market_boost_bonus = state.get("market_boost_bonus", 0.0)
                    self.market_peg_active = state.get("market_peg_active", False)
                    self.user_stats = state.get("user_stats", {})
            except Exception:
                pass

    def get_chain_length(self, coin_type="MAIN"):
        return self.storage.get_chain_length(coin_type)

    def get_last_block(self, coin_type="MAIN"):
        length = self.get_chain_length(coin_type)
        if length == 0:
            return None
        return self.storage.get_block(coin_type, length, full_data=True)

    def mint_block(self, proof, coin_type="MAIN", previous_hash=None, node_value_1_99=99, miner=None, variable_slot="VAR_GENESIS", variable_hash="0x0"):
        with self.lock:
            last = self.get_last_block(coin_type)
            prev_hash = previous_hash or (self.hash(last) if last else "1")
            txs = list(self.current_main_transactions if coin_type == "MAIN" else self.current_alt_transactions)

            block_miner = miner
            if not block_miner and txs:
                for t in txs:
                    if t.get("sender") == "0":
                        block_miner = t.get("recipient")
                        break

            mined_total = sum(int(t["amount"]) for t in txs if t.get("sender") == "0")
            if mined_total == 0 and coin_type == "MAIN" and block_miner:
                mined_total = self.BASE_MAIN_REWARD

            mined_powers = []
            for t in txs:
                if t.get("sender") == "0" and "powers" in t:
                    mined_powers.extend(t["powers"])

            block = {
                "index": (last["index"] + 1) if last else 1,
                "timestamp": int(time()),
                "transactions": txs,
                "proof": proof,
                "variable_hash": variable_hash,
                "previous_hash": prev_hash,
                "coin_type": coin_type,
                "miner": block_miner,
                "mined_amount": mined_total,
                "mined_powers": mined_powers
            }
            block["hash"] = self.hash(block)

            if coin_type == "MAIN":
                self.current_main_transactions = []
            else:
                self.current_alt_transactions = []

            return self.storage.allocate_block(
                block,
                node_assigned_value=node_value_1_99,
                variable_slot=variable_slot
            )

    def validate_and_accept_block(self, incoming_block):
        """Validates an external block's continuity, hash, rewards, and ECDSA signatures."""
        if not isinstance(incoming_block, dict):
            return False, "Invalid block payload."

        coin_type = incoming_block.get("coin_type")
        if coin_type not in ("MAIN", self.sub_coin_name):
            return False, "Unsupported coin type."

        try:
            incoming_index = int(incoming_block.get("index", 0))
        except Exception:
            return False, "Invalid block index."

        with self.lock:
            last = self.get_last_block(coin_type)
            expected_index = (int(last["index"]) + 1) if last else 1

            if incoming_index < expected_index:
                return False, "Block index already exists."
            if incoming_index > expected_index:
                return False, f"Out-of-order block: expected {expected_index}, got {incoming_index}."

            expected_prev_hash = self.hash(last) if last else "1"
            if incoming_block.get("previous_hash") != expected_prev_hash:
                return False, "Previous hash mismatch."

            recomputed_hash = self.hash(incoming_block)
            if incoming_block.get("hash") != recomputed_hash:
                return False, "Block hash verification failed."

            txs = incoming_block.get("transactions", [])
            if not isinstance(txs, list):
                return False, "Invalid transactions list."

            coinbase_total = 0
            for tx in txs:
                if not isinstance(tx, dict):
                    return False, "Malformed transaction entry."
                snd = str(tx.get("sender", "")).strip()
                amt = int(tx.get("amount", 0))
                if amt <= 0:
                    return False, "Transaction amount must be positive."

                if snd == "0":
                    coinbase_total += amt
                else:
                    if not verify_transaction_signature(tx):
                        return False, "Invalid ECDSA transaction signature."

            max_reward = self.BASE_MAIN_REWARD if coin_type == "MAIN" else 1
            if coinbase_total > max_reward:
                return False, f"Coinbase reward exceeds limit ({max_reward})."

            if int(incoming_block.get("mined_amount", 0)) > max_reward:
                return False, "Header mined_amount exceeds protocol reward limit."

            epoch = VariableRuleGovernor.get_current_epoch()
            slot = VariableRuleGovernor.assign_variable_slot(self.node_id, epoch)
            node_val = VariableRuleGovernor.assign_node_value_1_99(self.node_id, epoch)

            self.storage.allocate_block(
                incoming_block,
                node_assigned_value=node_val,
                epoch=epoch,
                variable_slot=slot
            )
            return True, f"Block #{incoming_index} ({coin_type}) accepted."

    def new_transaction(self, sender, recipient, amount, coin_type="MAIN", powers=None, private_key=None):
        try:
            amount = int(float(amount))
        except Exception:
            return False, "Invalid amount parameter."

        if amount <= 0:
            return False, "Amount must be strictly greater than zero."

        with self.lock:
            if sender != "0" and self.get_balance(sender, coin_type, True) < amount:
                return False, "Insufficient balance."

            tx_data = {
                "sender": sender,
                "recipient": recipient,
                "amount": amount,
                "coin_type": coin_type,
                "timestamp": int(time())
            }
            if powers is not None:
                tx_data["powers"] = [round(float(p), 9) for p in powers]

            if sender != "0" and private_key:
                try:
                    tx_data["signature"] = sign_transaction(private_key, tx_data)
                except Exception as e:
                    return False, f"Failed to sign transaction: {str(e)}"

            target_txs = self.current_main_transactions if coin_type == "MAIN" else self.current_alt_transactions
            target_txs.append(tx_data)
            return True, self.get_chain_length(coin_type) + 1

    @staticmethod
    def hash(block):
        excluded = (
            "hash", "status", "required_value_1_99", "node_value_1_99",
            "data_snapshot_hash", "cluster_id", "cluster_offset",
            "assigned_variable_slot", "block_variable_slot", "epoch",
            "transaction_count"
        )
        block_copy = {k: v for k, v in block.items() if k not in excluded}
        return hashlib.sha256(json.dumps(block_copy, sort_keys=True).encode("utf-8")).hexdigest()

    def get_user_stats(self, address):
        clean_addr = str(address).strip().lower()
        if clean_addr not in self.user_stats:
            self.user_stats[clean_addr] = {
                "personal_supply_offset": 0,
                "personal_burned": 0,
                "personal_boost": 0.0,
                "personal_peg_active": False
            }
        return self.user_stats[clean_addr]

    def get_balance(self, address, coin_type="MAIN", include_pending=True):
        if not address:
            return 0
        clean_addr = str(address).strip().lower()
        balance = 0
        all_blocks = self.storage.get_all_blocks(coin_type, include_passive_data=True)

        for block in all_blocks.values():
            block_miner = str(block.get("miner", "")).strip().lower()
            mined_amt = int(block.get("mined_amount", 0))
            is_block_winner = (block_miner == clean_addr and mined_amt > 0)

            if is_block_winner:
                balance += mined_amt

            txs = block.get("transactions", [])
            for tx in txs:
                if tx.get("coin_type", "MAIN") == coin_type:
                    snd = str(tx.get("sender", "")).strip().lower()
                    rec = str(tx.get("recipient", "")).strip().lower()
                    amt = int(tx.get("amount", 0))

                    if snd == "0" and is_block_winner and rec == clean_addr:
                        continue

                    if snd == clean_addr and snd != "0":
                        balance -= amt
                    if rec == clean_addr:
                        balance += amt

        if include_pending:
            pending_txs = self.current_main_transactions if coin_type == "MAIN" else self.current_alt_transactions
            for tx in pending_txs:
                snd = str(tx.get("sender", "")).strip().lower()
                rec = str(tx.get("recipient", "")).strip().lower()
                amt = int(tx.get("amount", 0))
                if snd == clean_addr and snd != "0":
                    balance -= amt
                if rec == clean_addr and snd != "0":
                    balance += amt

        return int(balance)

    def get_user_shield_tokens(self, address, include_pending=True):
        if not address:
            return []
        clean_addr = str(address).strip().lower()
        tokens = []
        all_blocks = self.storage.get_all_blocks(self.sub_coin_name, include_passive_data=True)

        for idx in sorted(all_blocks.keys()):
            block = all_blocks[idx]
            txs = block.get("transactions", [])

            if not txs and str(block.get("miner", "")).strip().lower() == clean_addr:
                header_powers = block.get("mined_powers", [])
                if header_powers:
                    tokens.extend([round(float(p), 9) for p in header_powers])
                else:
                    tokens.append(99.0)
                continue

            for tx in txs:
                if tx.get("coin_type") == self.sub_coin_name:
                    rec = str(tx.get("recipient", "")).strip().lower()
                    snd = str(tx.get("sender", "")).strip().lower()

                    if rec == clean_addr:
                        if "powers" in tx and isinstance(tx["powers"], list):
                            tokens.extend([round(float(p), 9) for p in tx["powers"]])
                        elif "power" in tx:
                            tokens.append(round(float(tx["power"]), 9))
                        else:
                            tokens.extend([99.0] * int(tx.get("amount", 1)))
                    if snd == clean_addr:
                        if "powers" in tx and isinstance(tx["powers"], list):
                            for p in tx["powers"]:
                                p_flt = round(float(p), 9)
                                if p_flt in tokens:
                                    tokens.remove(p_flt)
                        else:
                            amt = int(tx.get("amount", 1))
                            for _ in range(min(amt, len(tokens))):
                                tokens.pop(0)

        if include_pending:
            for tx in self.current_alt_transactions:
                if tx.get("coin_type") == self.sub_coin_name:
                    snd = str(tx.get("sender", "")).strip().lower()
                    rec = str(tx.get("recipient", "")).strip().lower()
                    if snd == clean_addr:
                        if "powers" in tx and isinstance(tx["powers"], list):
                            for p in tx["powers"]:
                                p_flt = round(float(p), 9)
                                if p_flt in tokens:
                                    tokens.remove(p_flt)
                        else:
                            amt = int(tx.get("amount", 1))
                            for _ in range(min(amt, len(tokens))):
                                tokens.pop(0)
                    if rec == clean_addr and snd != "0":
                        if "powers" in tx and isinstance(tx["powers"], list):
                            tokens.extend([round(float(p), 9) for p in tx["powers"]])
                        else:
                            tokens.extend([99.0] * int(tx.get("amount", 1)))

        return tokens

    def get_address_history(self, address):
        if not address:
            return []
        clean_addr = str(address).strip().lower()
        burn_addr = self.BURN_ADDRESS.lower()
        history = []

        for coin_label in ("MAIN", self.sub_coin_name):
            all_blocks = self.storage.get_all_blocks(coin_label, include_passive_data=True)
            for idx in sorted(all_blocks.keys()):
                block = all_blocks[idx]
                b_time = int(block.get("timestamp", 0))
                b_miner = str(block.get("miner", "")).strip().lower()
                mined_amt = int(block.get("mined_amount", 0))
                is_winner = (b_miner == clean_addr and mined_amt > 0)

                if is_winner:
                    history.append({
                        "type": "MINED",
                        "coin_type": coin_label,
                        "amount": mined_amt,
                        "counterparty": "PROTOCOL_REWARD",
                        "block_index": idx,
                        "timestamp": b_time,
                        "status": "CONFIRMED"
                    })

                for tx in block.get("transactions", []):
                    snd = str(tx.get("sender", "")).strip().lower()
                    rec = str(tx.get("recipient", "")).strip().lower()
                    amt = int(tx.get("amount", 0))
                    tx_time = int(tx.get("timestamp", b_time))

                    if snd == "0" and is_winner and rec == clean_addr:
                        continue

                    if snd == clean_addr and snd != "0":
                        tx_type = "BURNED" if rec == burn_addr else "SENT"
                        history.append({
                            "type": tx_type,
                            "coin_type": coin_label,
                            "amount": amt,
                            "counterparty": tx.get("recipient", ""),
                            "block_index": idx,
                            "timestamp": tx_time,
                            "status": "CONFIRMED"
                        })
                    elif rec == clean_addr:
                        tx_type = "MINED" if snd == "0" else "RECEIVED"
                        history.append({
                            "type": tx_type,
                            "coin_type": coin_label,
                            "amount": amt,
                            "counterparty": "PROTOCOL_REWARD" if snd == "0" else tx.get("sender", ""),
                            "block_index": idx,
                            "timestamp": tx_time,
                            "status": "CONFIRMED"
                        })

        pending_sets = [
            ("MAIN", self.current_main_transactions),
            (self.sub_coin_name, self.current_alt_transactions)
        ]
        for coin_label, p_list in pending_sets:
            next_idx = self.get_chain_length(coin_label) + 1
            for tx in p_list:
                snd = str(tx.get("sender", "")).strip().lower()
                rec = str(tx.get("recipient", "")).strip().lower()
                amt = int(tx.get("amount", 0))
                tx_time = int(tx.get("timestamp", int(time())))

                if snd == clean_addr and snd != "0":
                    tx_type = "BURNED" if rec == burn_addr else "SENT"
                    history.append({
                        "type": tx_type,
                        "coin_type": coin_label,
                        "amount": amt,
                        "counterparty": tx.get("recipient", ""),
                        "block_index": next_idx,
                        "timestamp": tx_time,
                        "status": "PENDING"
                    })
                elif rec == clean_addr and snd != "0":
                    history.append({
                        "type": "RECEIVED",
                        "coin_type": coin_label,
                        "amount": amt,
                        "counterparty": tx.get("sender", ""),
                        "block_index": next_idx,
                        "timestamp": tx_time,
                        "status": "PENDING"
                    })

        history.sort(key=lambda x: (x["timestamp"], x["block_index"]), reverse=True)
        return history[:100]

    def get_effective_max_supply(self, address=None):
        base = (self.BASE_MAX_MAIN + self.dynamic_supply_offset) - self.burned_main_coins
        if address:
            stats = self.get_user_stats(address)
            base += stats.get("personal_supply_offset", 0)
            base -= stats.get("personal_burned", 0)
        return int(base)

    def get_total_mined(self, coin_type="MAIN"):
        total = 0
        all_blocks = self.storage.get_all_blocks(coin_type, include_passive_data=True)
        for block in all_blocks.values():
            if "mined_amount" in block:
                total += int(block["mined_amount"])
            else:
                txs = block.get("transactions", [])
                for tx in txs:
                    if tx.get("coin_type", "MAIN") == coin_type and tx.get("sender") == "0":
                        total += int(tx["amount"])
        return int(total)

    def get_shield_impact_power(self):
        alt_mined = self.get_total_mined(self.sub_coin_name)
        if alt_mined <= 0:
            return 99.0

        if alt_mined < 1000:
            progress = alt_mined / 1000.0
            power = 99.0 - (progress * 29.0)
            return max(70.0, round(power, 4))
        elif alt_mined < 100000:
            progress = (alt_mined - 1000) / 99000.0
            power = 70.0 - (progress * 20.0)
            return max(50.0, round(power, 4))
        elif alt_mined < 4000000:
            progress = (alt_mined - 100000) / 3900000.0
            power = 50.0 - (progress * 20.0)
            return max(30.0, round(power, 4))
        elif alt_mined < 10000000:
            progress = (alt_mined - 4000000) / 6000000.0
            power = 30.0 - (progress * 20.0)
            return max(10.0, round(power, 4))
        elif alt_mined < 20000000:
            progress = (alt_mined - 10000000) / 10000000.0
            power = 10.0 - (progress * 9.0)
            return max(1.0, round(power, 4))
        else:
            excess = alt_mined - 20000000
            tier_step = int(excess // 10000000)
            fraction = (excess % 10000000) / 10000000.0
            base_power = 1.0 / (10.0 ** (tier_step + 1))
            next_power = base_power / 10.0
            power = base_power - (fraction * (base_power - next_power))
            return max(0.000000001, round(power, 9))

    def get_mining_power_shield(self, address=None):
        alt_mined = self.get_total_mined(self.sub_coin_name)
        progress = (alt_mined * 10.0) / float(self.BASE_MAX_MAIN)

        if progress < 1.0:
            power = 99.0 * (1.0 - progress)
        else:
            excess = alt_mined - 2100000
            power = 1.0 / (1.0 + (excess / 1000000.0))

        return max(0.0001, round(power, 4))

    def get_mining_power_main(self, address=None):
        total_mined = self.get_total_mined("MAIN")
        max_limit = self.get_effective_max_supply(address)
        if total_mined >= max_limit:
            return 0.0

        progress = total_mined / float(max_limit)
        power = 99.0 * (1.0 - progress)
        return max(0.0001, round(power, 4))


# =====================================================================
# P2P RELAY CLIENT HELPERS (VERSION-ENFORCED HEARTBEAT, PUSH & PULL)
# =====================================================================
app = Flask(__name__)
blockchain = Blockchain()
upnp_runtime_info = {"encrypted_external_endpoint": None}


def get_valid_relay_urls():
    """Returns configured relay URLs excluding placeholder domains."""
    return [u.rstrip("/") for u in PEER_RELAY_URLS if IPSecurityLayer.is_valid_host_config(u)]


def http_post_json(url, payload, timeout=PEER_TIMEOUT_SEC):
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={
            "Content-Type": "application/json",
            "User-Agent": f"VariableCoinNode/{APP_VERSION}",
            "X-VCP-Version": APP_VERSION
        },
        method="POST"
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def http_get_json(url, timeout=PEER_TIMEOUT_SEC):
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": f"VariableCoinNode/{APP_VERSION}",
            "X-VCP-Version": APP_VERSION
        },
        method="GET"
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def send_heartbeat_to_relays():
    """Announces this node's persistent node_id and version to active relay servers."""
    if SERVER_MODE == "web":
        return
    payload = {
        "node_id": blockchain.node_id,
        "client_version": APP_VERSION,
        "encrypted_endpoint": upnp_runtime_info.get("encrypted_external_endpoint"),
        "main_height": blockchain.get_chain_length("MAIN"),
        "alt_height": blockchain.get_chain_length(blockchain.sub_coin_name)
    }
    for base_url in get_valid_relay_urls():
        try:
            http_post_json(f"{base_url}/p2p/heartbeat", payload)
        except Exception:
            continue


def broadcast_block_to_relays(block):
    """Pushes a newly mined block to relay servers in the background."""
    if SERVER_MODE == "web":
        return

    def _push():
        payload = {
            "node_id": blockchain.node_id,
            "client_version": APP_VERSION,
            "block": block
        }
        for base_url in get_valid_relay_urls():
            try:
                http_post_json(f"{base_url}/p2p/submit_block", payload)
            except Exception:
                continue

    threading.Thread(target=_push, daemon=True).start()


def sync_chain_from_relays():
    """Pulls missing blocks from relay servers and validates them locally."""
    if SERVER_MODE == "web":
        return
    for base_url in get_valid_relay_urls():
        for coin_type in ("MAIN", blockchain.sub_coin_name):
            try:
                local_height = blockchain.get_chain_length(coin_type)
                url = f"{base_url}/p2p/blocks?coin={coin_type}&from_index={local_height + 1}"
                res = http_get_json(url)
                blocks = res.get("blocks", [])
                for blk in blocks:
                    ok, _ = blockchain.validate_and_accept_block(blk)
                    if not ok:
                        break
            except Exception:
                continue


# =====================================================================
# FLASK API, RATE LIMITER, VERSION GUARD & P2P ENDPOINTS
# =====================================================================
_rate_limit_lock = threading.Lock()
_rate_limit_buckets = {}


def get_client_ip():
    return (
        request.headers.get("CF-Connecting-IP")
        or request.headers.get("X-Forwarded-For", "").split(",")[0].strip()
        or request.remote_addr
        or "unknown"
    )


def check_rate_limit(bucket_name, max_requests=60, window_sec=60):
    """Lightweight in-memory IP rate limiter for public web mode."""
    if SERVER_MODE != "web":
        return None
    client_ip = get_client_ip()
    now = time()
    key = (bucket_name, client_ip)
    with _rate_limit_lock:
        timestamps = [t for t in _rate_limit_buckets.get(key, []) if now - t < window_sec]
        if len(timestamps) >= max_requests:
            _rate_limit_buckets[key] = timestamps
            return jsonify({"error": "Too many requests. Please wait a moment and try again."}), 429
        timestamps.append(now)
        _rate_limit_buckets[key] = timestamps
    return None


def require_desktop_mode():
    """Blocks sensitive write/mining endpoints when running as the public web portal."""
    if SERVER_MODE == "web":
        return jsonify({
            "error": "This action is disabled on the public web portal for security. Please download and use the Desktop Node."
        }), 403
    return None


def require_supported_version(payload=None):
    """Rejects outdated clients on P2P write endpoints to prevent version exploits."""
    client_ver = (
        request.headers.get("X-VCP-Version")
        or (payload.get("client_version") if isinstance(payload, dict) else None)
        or "0.0.0"
    )
    if not VersionManager.is_version_supported(client_ver, MIN_SUPPORTED_VERSION):
        return jsonify({
            "status": "upgrade_required",
            "error": f"Client version {client_ver} is outdated. Minimum supported version is {MIN_SUPPORTED_VERSION}.",
            "min_supported_version": MIN_SUPPORTED_VERSION,
            "latest_version": APP_VERSION,
            "exe_download_url": f"{PRIMARY_DOMAIN}/download/exe"
        }), 426
    return None


@app.route("/")
def index():
    return render_template("index.html", server_mode=SERVER_MODE, app_version=APP_VERSION)


@app.route("/api/version", methods=["GET"])
def api_version():
    limited = check_rate_limit("version", max_requests=60, window_sec=60)
    if limited:
        return limited
    return jsonify({
        "latest_version": APP_VERSION,
        "min_supported_version": MIN_SUPPORTED_VERSION,
        "zip_download_url": f"{PRIMARY_DOMAIN}/download",
        "exe_download_url": f"{PRIMARY_DOMAIN}/download/exe"
    }), 200


@app.route("/download")
def download_node():
    limited = check_rate_limit("download", max_requests=10, window_sec=60)
    if limited:
        return limited
    if os.path.isfile(DESKTOP_ZIP_PATH):
        return send_file(
            DESKTOP_ZIP_PATH,
            as_attachment=True,
            download_name=os.path.basename(DESKTOP_ZIP_PATH)
        )
    return jsonify({
        "status": "unavailable",
        "message": "Desktop Node package (.zip) is not currently uploaded on the server."
    }), 404


@app.route("/download/exe")
def download_node_exe():
    limited = check_rate_limit("download_exe", max_requests=10, window_sec=60)
    if limited:
        return limited
    if os.path.isfile(DESKTOP_EXE_PATH):
        return send_file(
            DESKTOP_EXE_PATH,
            as_attachment=True,
            download_name=os.path.basename(DESKTOP_EXE_PATH)
        )
    return jsonify({
        "status": "unavailable",
        "message": "Desktop Node binary (.exe) is not currently uploaded on the server."
    }), 404


# --- P2P Synchronization & Node Registry Endpoints ---
@app.route("/p2p/heartbeat", methods=["POST"])
def api_p2p_heartbeat():
    limited = check_rate_limit("p2p_heartbeat", max_requests=30, window_sec=60)
    if limited:
        return limited
    data = request.get_json() or {}
    outdated = require_supported_version(data)
    if outdated:
        return outdated

    node_id = str(data.get("node_id", "")).strip()
    enc_ep = data.get("encrypted_endpoint")
    client_ver = request.headers.get("X-VCP-Version") or data.get("client_version", APP_VERSION)
    if not node_id.startswith("NODE_"):
        return jsonify({"error": "Invalid node_id format."}), 400

    blockchain.register_node_heartbeat(node_id, get_client_ip(), enc_ep, client_ver)
    return jsonify({
        "status": "ok",
        "active_nodes_count": blockchain.get_active_peers_count(),
        "main_height": blockchain.get_chain_length("MAIN"),
        "alt_height": blockchain.get_chain_length(blockchain.sub_coin_name),
        "latest_version": APP_VERSION
    }), 200


@app.route("/p2p/peers", methods=["GET"])
def api_p2p_peers():
    limited = check_rate_limit("p2p_peers", max_requests=30, window_sec=60)
    if limited:
        return limited
    return jsonify({
        "node_id": blockchain.node_id,
        "active_nodes_count": blockchain.get_active_peers_count(),
        "peers": blockchain.get_active_nodes_snapshot()
    }), 200


@app.route("/p2p/blocks", methods=["GET"])
def api_p2p_blocks():
    limited = check_rate_limit("p2p_blocks", max_requests=60, window_sec=60)
    if limited:
        return limited
    coin_type = request.args.get("coin", "MAIN").strip()
    if coin_type not in ("MAIN", blockchain.sub_coin_name):
        return jsonify({"error": "Invalid coin type."}), 400
    try:
        from_index = max(1, int(request.args.get("from_index", 1)))
    except Exception:
        return jsonify({"error": "Invalid from_index parameter."}), 400

    chain_len = blockchain.get_chain_length(coin_type)
    max_batch = 50
    end_index = min(chain_len, from_index + max_batch - 1)
    blocks = []
    for idx in range(from_index, end_index + 1):
        blk = blockchain.storage.get_block(coin_type, idx, full_data=True)
        if blk:
            blocks.append(blk)

    return jsonify({
        "coin_type": coin_type,
        "chain_height": chain_len,
        "from_index": from_index,
        "blocks": blocks
    }), 200


@app.route("/p2p/submit_block", methods=["POST"])
def api_p2p_submit_block():
    limited = check_rate_limit("p2p_submit", max_requests=20, window_sec=60)
    if limited:
        return limited
    data = request.get_json() or {}
    outdated = require_supported_version(data)
    if outdated:
        return outdated

    node_id = str(data.get("node_id", "")).strip()
    block = data.get("block")
    client_ver = request.headers.get("X-VCP-Version") or data.get("client_version", APP_VERSION)

    if node_id.startswith("NODE_"):
        blockchain.register_node_heartbeat(node_id, get_client_ip(), client_version=client_ver)

    ok, msg = blockchain.validate_and_accept_block(block)
    if not ok:
        return jsonify({"status": "rejected", "error": msg}), 400
    return jsonify({"status": "accepted", "message": msg}), 200


# --- Wallet, Explorer, Mining & Protocol Endpoints ---
@app.route("/wallet/new", methods=["GET"])
def api_new_wallet():
    blocked = require_desktop_mode()
    if blocked:
        return blocked
    wallet = generate_master_wallet()
    return jsonify(wallet), 200


@app.route("/wallet/recover", methods=["POST"])
def api_recover_wallet():
    blocked = require_desktop_mode()
    if blocked:
        return blocked
    data = request.get_json() or {}
    priv_key = data.get("private_key", "")
    sk_hex, vk_hex, err = wallet_from_private_key(priv_key)
    if err:
        return jsonify({"error": err}), 400
    return jsonify({
        "public_key": vk_hex,
        "private_key": sk_hex
    }), 200


@app.route("/chain", methods=["GET"])
def api_get_chain():
    limited = check_rate_limit("chain", max_requests=60, window_sec=60)
    if limited:
        return limited

    address = request.args.get("address", "").strip()

    main_len = blockchain.get_chain_length("MAIN")
    alt_len = blockchain.get_chain_length(blockchain.sub_coin_name)
    main_supply = blockchain.get_total_mined("MAIN")
    alt_circulating = blockchain.get_total_mined(blockchain.sub_coin_name)
    current_mint_power = blockchain.get_shield_impact_power()
    active_nodes = blockchain.get_active_peers_count()

    response_data = {
        "1_GLOBAL_DATA": {
            "main_chain_height": main_len,
            "alt_chain_height": alt_len,
            "main_coin_supply": f"{main_supply} / {blockchain.get_effective_max_supply()}",
            "shield_coin_circulating": f"{alt_circulating} Units",
            "current_network_mint_power": current_mint_power,
            "active_nodes_count": active_nodes,
            "server_mode": SERVER_MODE,
            "app_version": APP_VERSION
        }
    }

    if address:
        main_bal = blockchain.get_balance(address, "MAIN", include_pending=True)
        shield_tokens = blockchain.get_user_shield_tokens(address, include_pending=True)

        total_shield_count = len(shield_tokens)
        overall_avg_power = round(sum(shield_tokens) / total_shield_count, 4) if total_shield_count > 0 else 0.0

        tiers = {
            "tier_99_70": {"count": 0, "powers": []},
            "tier_70_50": {"count": 0, "powers": []},
            "tier_50_30": {"count": 0, "powers": []},
            "tier_30_10": {"count": 0, "powers": []},
            "tier_10_1": {"count": 0, "powers": []},
            "tier_below_1": {"count": 0, "powers": []}
        }

        for p in shield_tokens:
            tier_key = get_tier_for_power(p)
            if tier_key in tiers:
                tiers[tier_key]["count"] += 1
                tiers[tier_key]["powers"].append(p)

        tier_summary = {}
        for t_key, t_data in tiers.items():
            cnt = t_data["count"]
            avg_p = round(sum(t_data["powers"]) / cnt, 4) if cnt > 0 else 0.0
            tier_summary[t_key] = {
                "count": cnt,
                "average_power": avg_p
            }

        response_data["2_USER_DATA"] = {
            "address": address,
            "main_coin_balance": main_bal,
            "shield_coin_balance": total_shield_count,
            "shield_overall_average_power": overall_avg_power,
            "tiers": tier_summary,
            "all_tokens_sorted": sorted(shield_tokens, reverse=True),
            "history": blockchain.get_address_history(address)
        }

    return jsonify(response_data), 200


@app.route("/history", methods=["GET"])
def api_get_history():
    limited = check_rate_limit("history", max_requests=60, window_sec=60)
    if limited:
        return limited
    address = request.args.get("address", "").strip()
    if not address:
        return jsonify({"error": "Wallet address is required."}), 400
    return jsonify({
        "address": address,
        "history": blockchain.get_address_history(address)
    }), 200


@app.route("/transfer", methods=["POST"])
def api_transfer():
    blocked = require_desktop_mode()
    if blocked:
        return blocked

    data = request.get_json() or {}
    sender = data.get("sender", "").strip()
    recipient = data.get("recipient", "").strip()
    priv_key = data.get("private_key", "").strip()
    coin_input = data.get("coin_type", "MAIN").strip()
    requested_power_raw = data.get("requested_power", None)
    accept_closest = bool(data.get("accept_closest", False))

    try:
        amount = int(float(data.get("amount", 0)))
    except Exception:
        return jsonify({"error": "Invalid transfer amount."}), 400

    if not sender or not recipient or not priv_key:
        return jsonify({"error": "Sender address, recipient address, and private key are required."}), 400

    if sender.lower() == recipient.lower():
        return jsonify({"error": "Sender and recipient addresses cannot be identical."}), 400

    if amount <= 0:
        return jsonify({"error": "Transfer amount must be greater than zero."}), 400

    if not verify_key_match(priv_key, sender):
        return jsonify({"error": "Cryptographic signature verification failed: Invalid private key for sender wallet."}), 401

    target_coin = blockchain.sub_coin_name if coin_input in ("ALT", "SHIELD_COIN") else "MAIN"
    selected_powers = None

    with blockchain.lock:
        if target_coin == blockchain.sub_coin_name:
            user_tokens = blockchain.get_user_shield_tokens(sender, include_pending=True)
            if len(user_tokens) < amount:
                return jsonify({
                    "error": f"Insufficient Shield Coin balance ({len(user_tokens)} total units available in wallet)."
                }), 400

            if requested_power_raw is None or str(requested_power_raw).strip() == "":
                return jsonify({
                    "error": "Please enter the target Impact Power you wish to transfer."
                }), 400

            try:
                req_power = round(float(requested_power_raw), 4)
            except Exception:
                return jsonify({"error": "Invalid Impact Power value entered."}), 400

            if req_power <= 0 or req_power > 99.0:
                return jsonify({"error": "Requested Impact Power must be between 0.0001 and 99.0."}), 400

            exact_matches = [p for p in user_tokens if abs(round(float(p), 4) - req_power) < 1e-6]

            if len(exact_matches) >= amount:
                selected_powers = exact_matches[:amount]
            else:
                sorted_by_closest = sorted(
                    user_tokens,
                    key=lambda p: (abs(round(float(p), 4) - req_power), -float(p))
                )
                closest_tokens = [round(float(p), 4) for p in sorted_by_closest[:amount]]

                if not accept_closest:
                    return jsonify({
                        "status": "closest_suggestion",
                        "requested_power": req_power,
                        "amount": amount,
                        "exact_match_count": len(exact_matches),
                        "closest_powers": closest_tokens,
                        "closest_average_power": round(sum(closest_tokens) / len(closest_tokens), 4),
                        "message": (
                            f"Exact impact power {req_power} is not available for {amount} unit(s). "
                            f"Closest available token power(s) in your wallet: {', '.join(str(p) for p in closest_tokens)}"
                        )
                    }), 200

                selected_powers = sorted_by_closest[:amount]

        success, tx_res = blockchain.new_transaction(
            sender=sender,
            recipient=recipient,
            amount=amount,
            coin_type=target_coin,
            powers=selected_powers,
            private_key=priv_key
        )

    if not success:
        return jsonify({"error": tx_res}), 400

    return jsonify({
        "status": "success",
        "coin_type": target_coin,
        "amount": amount,
        "transferred_powers": [round(float(p), 4) for p in selected_powers] if selected_powers else [],
        "scheduled_block": tx_res
    }), 200


@app.route("/mine", methods=["GET"])
def api_mine():
    blocked = require_desktop_mode()
    if blocked:
        return blocked

    address = request.args.get("address", "").strip()
    coin_type = request.args.get("coin", "ALT").strip()

    if not address:
        return jsonify({"error": "Miner address is required."}), 400

    target_coin = blockchain.sub_coin_name if coin_type == "ALT" else "MAIN"
    epoch = VariableRuleGovernor.get_current_epoch()
    slot = VariableRuleGovernor.assign_variable_slot(blockchain.node_id, epoch)
    node_val = VariableRuleGovernor.assign_node_value_1_99(blockchain.node_id, epoch)

    if target_coin == blockchain.sub_coin_name:
        mining_power = blockchain.get_mining_power_shield(address)
    else:
        mining_power = blockchain.get_mining_power_main(address)
        if mining_power <= 0:
            return jsonify({"error": "Maximum supply limit reached for Main Coin."}), 400

    seed_id = f"BLOCK_MINT_{target_coin}_{blockchain.get_chain_length(target_coin) + 1}"
    var_hash, attempts, _ = VariableMiningEngine.search_variable(
        seed_id, mining_power, slot, node_val, target_coin
    )

    if not var_hash:
        return jsonify({"status": "failed", "message": "Mining target not reached within cycle bounds. Please retry."}), 500

    proof = random.randint(100000, 999999)
    mined_power_val = None
    reward_amount = blockchain.BASE_MAIN_REWARD

    with blockchain.lock:
        if target_coin == blockchain.sub_coin_name:
            mined_power_val = round(blockchain.get_shield_impact_power(), 4)
            reward_amount = 1
            blockchain.new_transaction(
                sender="0",
                recipient=address,
                amount=1,
                coin_type=target_coin,
                powers=[mined_power_val]
            )
        else:
            blockchain.new_transaction(
                sender="0",
                recipient=address,
                amount=blockchain.BASE_MAIN_REWARD,
                coin_type=target_coin
            )

        minted_block = blockchain.mint_block(
            proof=proof,
            coin_type=target_coin,
            miner=address,
            node_value_1_99=node_val,
            variable_slot=slot,
            variable_hash=var_hash
        )

    broadcast_block_to_relays(minted_block)

    return jsonify({
        "status": "success",
        "coin_type": target_coin,
        "block_mined": minted_block.get("index"),
        "reward_amount": reward_amount,
        "mined_power": mined_power_val,
        "mining_power_1_99": mining_power
    }), 200


@app.route("/protocol/act", methods=["POST"])
def api_protocol_act():
    blocked = require_desktop_mode()
    if blocked:
        return blocked

    data = request.get_json() or {}
    addr = data.get("address", "").strip()
    priv_key = data.get("private_key", "").strip()
    action = data.get("action", "").strip()
    requested_scope = data.get("scope", "global").strip().lower()
    target_tier = data.get("target_tier", "any").strip()
    burn_count = data.get("burn_count")
    alt_percentage_raw = data.get("alt_percentage", 100.0)

    valid_actions = ("peg_static", "boost_price", "discount_price", "burn_main", "expand_supply")
    if action not in valid_actions:
        return jsonify({"error": "Invalid protocol action."}), 400

    if not verify_key_match(priv_key, addr):
        return jsonify({"error": "Cryptographic signature validation failed: Private key does not match address."}), 401

    try:
        alt_percentage = float(alt_percentage_raw)
        if alt_percentage <= 0.0 or alt_percentage > 100.0:
            return jsonify({"error": "Percentage must be between 1 and 100."}), 400
    except Exception:
        return jsonify({"error": "Invalid percentage value."}), 400

    with blockchain.lock:
        shield_tokens = blockchain.get_user_shield_tokens(addr, include_pending=True)
        if not shield_tokens:
            return jsonify({"error": "No Shield tokens available in wallet to execute protocol action."}), 400

        if target_tier == "any":
            eligible_tokens = list(shield_tokens)
        else:
            eligible_tokens = [p for p in shield_tokens if get_tier_for_power(p) == target_tier]

        if not eligible_tokens:
            return jsonify({"error": f"No tokens found in selected tier ({target_tier})."}), 400

        if burn_count is not None and str(burn_count).strip() != "":
            try:
                requested_qty = int(burn_count)
                if requested_qty <= 0:
                    return jsonify({"error": "burn_count must be greater than zero."}), 400
                burn_qty = min(requested_qty, len(eligible_tokens))
            except Exception:
                return jsonify({"error": "Invalid burn_count value."}), 400
        elif alt_percentage < 100.0:
            burn_qty = max(1, int(len(eligible_tokens) * (alt_percentage / 100.0)))
        else:
            burn_qty = len(eligible_tokens)

        tokens_to_burn = eligible_tokens[:burn_qty]

        success, tx_res = blockchain.new_transaction(
            sender=addr,
            recipient=blockchain.BURN_ADDRESS,
            amount=len(tokens_to_burn),
            coin_type=blockchain.sub_coin_name,
            powers=tokens_to_burn,
            private_key=priv_key
        )

        if not success:
            return jsonify({"error": f"Transaction failure: {tx_res}"}), 400

        effect_magnitude = sum(tokens_to_burn) * 0.05

        if action in ("burn_main", "expand_supply"):
            effective_scope = "global"
        else:
            effective_scope = "personal" if requested_scope == "personal" else "global"

        stats = blockchain.get_user_stats(addr)

        if action == "peg_static":
            if effective_scope == "global":
                blockchain.market_peg_active = True
                blockchain.market_boost_bonus += (effect_magnitude * 0.1)
            else:
                stats["personal_peg_active"] = True
                stats["personal_boost"] = stats.get("personal_boost", 0.0) + (effect_magnitude * 0.1)
        elif action == "boost_price":
            if effective_scope == "global":
                blockchain.market_boost_bonus += effect_magnitude
            else:
                stats["personal_boost"] = stats.get("personal_boost", 0.0) + effect_magnitude
        elif action == "discount_price":
            if effective_scope == "global":
                blockchain.market_boost_bonus = max(0.0, blockchain.market_boost_bonus - effect_magnitude)
            else:
                stats["personal_boost"] = max(0.0, stats.get("personal_boost", 0.0) - effect_magnitude)
        elif action == "burn_main":
            blockchain.burned_main_coins += int(sum(tokens_to_burn) * 10)
        elif action == "expand_supply":
            blockchain.dynamic_supply_offset += int(sum(tokens_to_burn) * 50)

        blockchain.save_protocol_state()

    return jsonify({
        "status": "success",
        "action_executed": action,
        "scope": effective_scope.upper(),
        "tokens_burned_count": len(tokens_to_burn),
        "target_tier": target_tier,
        "burned_average_power": round(sum(tokens_to_burn) / len(tokens_to_burn), 4) if tokens_to_burn else 0.0,
        "protocol_state_updated": True
    }), 200


def background_p2p_daemon():
    """Handles daily epoch rotation, stale node pruning, heartbeats, and relay sync."""
    last_epoch = VariableRuleGovernor.get_current_epoch()
    while True:
        try:
            current_epoch = VariableRuleGovernor.get_current_epoch()
            if current_epoch != last_epoch:
                new_slot = VariableRuleGovernor.assign_variable_slot(blockchain.node_id, current_epoch)
                new_val = VariableRuleGovernor.assign_node_value_1_99(blockchain.node_id, current_epoch)
                blockchain.storage.rotate_all_blocks_for_new_epoch(new_val, current_epoch, new_slot)
                last_epoch = current_epoch

            blockchain.prune_stale_nodes()

            if SERVER_MODE == "desktop":
                send_heartbeat_to_relays()
                sync_chain_from_relays()
        except Exception:
            pass
        sleep(HEARTBEAT_INTERVAL_SEC)


if __name__ == "__main__":
    if SERVER_MODE == "desktop":
        AutoUpdater.check_and_apply_update()

    upnp_res = NodeIdentityAndUPnPManager.configure_upnp_ports(DEFAULT_TCP_PORT, DEFAULT_UDP_PORT)
    upnp_runtime_info["encrypted_external_endpoint"] = upnp_res.get("encrypted_external_endpoint")

    print(f"[NODE IDENTITY] ID: {blockchain.node_id} | MODE: {SERVER_MODE.upper()} | VERSION: {APP_VERSION}")
    print(f"[UPnP STATUS] {upnp_res.get('status_message')}")

    p2p_thread = threading.Thread(target=background_p2p_daemon, daemon=True)
    p2p_thread.start()

    if SERVER_MODE == "web":
        print(f"[SERVER START] Public Web Portal & Relay Node running on 0.0.0.0:{DEFAULT_HTTP_PORT}")
        print("[TIP] For production, run behind Nginx + Gunicorn (Linux) or Waitress (Windows).")
        app.run(host="0.0.0.0", port=DEFAULT_HTTP_PORT, debug=False, threaded=True)
    else:
        print(f"[SERVER START] Local Desktop Node running on http://127.0.0.1:{DEFAULT_HTTP_PORT}")

        def start_server():
            app.run(host="127.0.0.1", port=DEFAULT_HTTP_PORT, debug=False, threaded=True, use_reloader=False)

        threading.Thread(target=start_server, daemon=True).start()
        if webview is not None:
            webview.create_window(
                "Variable Coin Protocol Center",
                f"http://127.0.0.1:{DEFAULT_HTTP_PORT}",
                width=1200,
                height=800
            )
            webview.start()
        else:
            start_server()
