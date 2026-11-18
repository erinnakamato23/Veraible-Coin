# VariableCoin: A Peer-to-Peer Electronic Cash and Algorithmic Valuation System Governed by the 1–99 Infinite Variable Rule

**Abstract.** Conventional cryptocurrencies rely entirely on external, speculative order books where asset valuation is dictated by volatile supply-and-demand shocks, while underlying nodes suffer from unbounded memory bloat, thermal degradation, and plaintext IP address exposure. We propose VariableCoin, a sovereign peer-to-peer protocol that decouples asset valuation from raw market supply and demand through an internal, cryptographically enforced helper-token mechanism (`SHIELD_COIN`), while governing all network operations through the **1–99 Variable Rule** across an **Infinite Variable** coordinate system. By binding proof-of-work mining searches, diminishing helper-token power tiers, dynamic RAM/disk state projection, and stream-cipher IP obfuscation to a unified 1–99 mathematical scale and an unbounded 2^256 variable domain, VariableCoin achieves deterministic price stabilization, hardware-aware full-archive validation, and zero-plaintext peer routing without trusted intermediaries.

---

## 1. Introduction: Decoupling Valuation from Supply and Demand

In traditional financial and cryptocurrency markets, the price of an asset is an external artifact of order-book liquidity. Speculative sell-offs, cascading liquidations, and macroeconomic shocks routinely destroy the purchasing power of holders regardless of the underlying protocol's cryptographic integrity. Existing blockchains treat price as an exogenous metric; the ledger merely records transfers while remaining blind to valuation collapse.

VariableCoin resolves this fundamental limitation by internalizing valuation mechanics directly into the consensus state machine. Instead of leaving valuation to unmoderated supply-and-demand forces, VariableCoin introduces a dual-asset state engine:
1. **Main Coin (`MAIN`):** A store-of-value asset with a baseline maximum supply of 21,000,000 units and a fixed block reward of 50 units.
2. **Shield Coin (`SHIELD_COIN`):** A power-sealed algorithmic utility asset whose inception power begins at 99.0 and decays deterministically across cumulative issuance milestones.

Holders do not need to rely on external buyers to defend or appreciation-adjust their portfolio valuation. By permanently burning Shield Coins from specific power tiers to an unrecoverable burn address (`0x000000000000000000000000000000000000dEaD`), participants directly mutate protocol state parameters—pegging valuation floors (`peg_static`), increasing valuation coefficients (`boost_price`), applying discount coefficients (`discount_price`), contracting effective supply (`burn_main`), or expanding capacity limits (`expand_supply`) at either a personal wallet scope or a global network scope.

---

## 2. The 1–99 Variable Rule and the Infinite Variable Architecture

At the core of the VariableCoin protocol is the mathematical duality between the **Infinite Variable** domain and the **1–99 Variable Rule**. Rather than operating on static data structures, every peer node and every ledger block is dynamically mapped into an unbounded cryptographic coordinate system that rotates every 24-hour epoch:

E = floor(t / 86400)

where t is the current Unix timestamp in seconds.

### 2.1 The Infinite Variable Domain
For any given epoch E, the protocol generates an unbounded set of deterministic coordinates—referred to as the **Infinite Variable** (VAR_1, VAR_2, ..., VAR_{2^256 - 1}). Each node with persistent identity ID_node and each block at height h for asset C is assigned a unique coordinate within the Infinite Variable:

Slot_node = VAR_{int(SHA256("UNBOUNDED_VARIABLE_SLOT_" || ID_node || E))}
Slot_block = VAR_{int(SHA256("BLOCK_VARIABLE_SLOT_" || C || h || E))}

Because the coordinate space spans 2^256 possible variable states, collisions are computationally infeasible, allowing the protocol to scale across an infinite number of variable assignments without central coordination.

### 2.2 The 1–99 Operational Scale
While the addressing domain is an **Infinite Variable**, all operational weights, resource thresholds, mining acceptance windows, and token inception powers are strictly bounded by the **1–99 Variable Rule**—a normalized continuous or integer interval [1, 99]. Across the protocol, 99 represents maximum active capacity, maximum inception impact power, and maximum mining accessibility, whereas 1 (and its asymptotic sub-unit extensions) represents minimum baseline footprint and maximum cryptographic difficulty.

Every 24-hour epoch, each node is assigned a deterministic baseline active ratio V_assigned in {1, 2, ..., 99}:

V_assigned = (int(SHA256("VARIABLE_RULE_1_99_" || ID_node || E)) mod 99) + 1

This single mathematical rule unifies four critical subsystems of the blockchain:
* **Helper Coin Economics:** Inception power starts at 99.0 and decays through tiered milestones toward 1.0 and into an asymptotic decimal tail.
* **Infinite Variable Mining:** Proof-of-work searches for a variable point within [0, 99.0) governed by a polynomial acceptance curve of the 1–99 mining power.
* **IP Address Discovery & Obfuscation:** Peer endpoints are encrypted and routed through epoch-keyed variable slots so raw IP addresses are never exposed.
* **Hardware & Memory Governance:** Blocks transition between ACTIVE (in-memory) and PASSIVE (disk-anchored) states by comparing the node's effective 1–99 value against each block's 1–99 requirement.

---

## 3. Dual-Asset Economics and Diminishing Power Tiers

To prevent arbitrary inflation of protocol-mutating authority, Shield Coin (`SHIELD_COIN`) is engineered with **diminishing inception power**. Whenever a Shield Coin block is mined, the newly minted token permanently seals the network's current impact power P_impact into its transaction payload. Once sealed at inception, a token's individual power never decays in the holder's wallet, creating distinct historical power tiers.

### 3.1 The Six-Tier Diminishing Power Schedule
Let S_alt denote the total cumulative circulating supply of Shield Coin mined across the network. The inception impact power P_impact(S_alt) is governed by a piecewise linear and exponential damping function anchored to the 1–99 scale:

1. **Tier 1 — Legendary Tokens (70.0 <= P_impact <= 99.0):** For 0 <= S_alt < 1,000:
   P_impact = 99.0 - 29.0 * (S_alt / 1000)

2. **Tier 2 — High Tokens (50.0 <= P_impact < 70.0):** For 1,000 <= S_alt < 100,000:
   P_impact = 70.0 - 20.0 * ((S_alt - 1000) / 99000)

3. **Tier 3 — Medium Tokens (30.0 <= P_impact < 50.0):** For 100,000 <= S_alt < 4,000,000:
   P_impact = 50.0 - 20.0 * ((S_alt - 100000) / 3900000)

4. **Tier 4 — Low Tokens (10.0 <= P_impact < 30.0):** For 4,000,000 <= S_alt < 10,000,000:
   P_impact = 30.0 - 20.0 * ((S_alt - 4000000) / 6000000)

5. **Tier 5 — Weak Tokens (1.0 <= P_impact < 10.0):** For 10,000,000 <= S_alt < 20,000,000:
   P_impact = 10.0 - 9.0 * ((S_alt - 10000000) / 10000000)

6. **Tier 6 — Asymptotic Infinite Variable Floor (P_impact < 1.0):** Once cumulative issuance reaches S_alt >= 20,000,000, the protocol enters an unbounded decimal damping regime where power scales down by an order of magnitude every 10,000,000 coins down to a hard cryptographic floor of 10^-9 (0.000000001):
   k = floor((S_alt - 20000000) / 10000000)
   f = ((S_alt - 20000000) mod 10000000) / 10000000
   P_base = 10^{-(k+1)}
   P_impact = max(10^-9, P_base - f * (P_base - P_base / 10))

| Tier Bracket | Supply Milestone (S_alt) | Inception Power Range | Protocol Classification |
| :--- | :--- | :--- | :--- |
| Tier 1 | 0 - 1,000 | 99.0000 -> 70.0000 | tier_99_70 (Legendary) |
| Tier 2 | 1,000 - 100,000 | 70.0000 -> 50.0000 | tier_70_50 (High) |
| Tier 3 | 100,000 - 4,000,000 | 50.0000 -> 30.0000 | tier_50_30 (Medium) |
| Tier 4 | 4,000,000 - 10,000,000 | 30.0000 -> 10.0000 | tier_30_10 (Low) |
| Tier 5 | 10,000,000 - 20,000,000 | 10.0000 -> 1.0000 | tier_10_1 (Weak) |
| Tier 6 | 20,000,000+ (Unbounded) | 0.1000 -> 0.000000001 | tier_below_1 (Asymptotic) |

---

## 4. Algorithmic Valuation and Protocol State Mutation

Because every Shield Coin carries its exact inception power p_i inside the UTXO/account inventory vector, a wallet holder possesses a granular portfolio of tokens across Tiers 1 through 6. To execute a protocol action, the user signs a burn transaction with their 256-bit SECP256k1 private key, selecting a target tier (`target_tier`), an execution scope (`personal` or `global`), and a quantity m (or percentage) of tokens to route to `0x000000000000000000000000000000000000dEaD`.

Let B = {p_1, p_2, ..., p_m} be the subset of Shield tokens burned in the transaction, and let W = sum(p_i) be the aggregate burned power. The protocol calculates the base mutation magnitude M = 0.05 * W and updates the valuation and supply state without any external price feed or order book:

* **Price Pegging (`peg_static`):** Activates the protocol stabilization lock (`market_peg_active = True`) and increments the baseline valuation coefficient by 0.1 * M, preventing downward market drift.
* **Valuation Boost (`boost_price`):** Directly increases the protocol's valuation boost coefficient by +0.05 * W.
* **Valuation Discount (`discount_price`):** Reduces the valuation boost coefficient down to a non-negative floor of 0.0: B_boost' = max(0.0, B_boost - 0.05 * W).
* **Main Supply Contraction (`burn_main`):** Permanently reduces the effective maximum supply ceiling of Main Coin by 10 * W units (applied either to `burned_main_coins` globally or `personal_burned` locally).
* **Main Capacity Expansion (`expand_supply`):** Expands the effective maximum Main Coin ceiling by 50 * W units (applied either to `dynamic_supply_offset` globally or `personal_supply_offset` locally):
  S_{max, eff}(u) = (21,000,000 + Offset_global - Burned_global) + (Offset_personal(u) - Burned_personal(u))

Through this mechanism, early adopters who mine high-tier Shield Coins (near 99.0 power) acquire concentrated stabilization authority, whereas late-stage participants can aggregate larger quantities of lower-tier tokens to achieve equivalent state mutations.

---

## 5. Proof-of-Work in the Infinite Variable Matrix

Traditional proof-of-work algorithms require miners to brute-force SHA-256 nonces in search of a block header hash with a predetermined number of leading zeros. VariableCoin replaces static bit-prefix matching with **Infinite Variable Search** (`VariableMiningEngine`), governed directly by the **1–99 Variable Rule**.

### 5.1 Decoupled 1–99 Mining Power Curves
Rather than using a single difficulty adjustment algorithm for both assets, VariableCoin decouples the mining power P_mine in (0, 99.0] of Main Coin and Shield Coin:

1. **Main Coin Mining Power (P_{mine, MAIN}):** Scales linearly from 99.0 down to 0.0001 (and 0.0 upon reaching the effective supply cap S_{max, eff}):
   P_{mine, MAIN} = max(0.0001, 99.0 * (1.0 - S_{mined, MAIN} / S_{max, eff}))

2. **Shield Coin Mining Power (P_{mine, SHIELD}):** Scales 10x faster than Main Coin across an initial 2,100,000 unit baseline, and then transitions smoothly into an inverse hyperbolic tail so Shield Coin remains mineable indefinitely across the Infinite Variable space:
   progress = (10.0 * S_alt) / 21,000,000
   If progress < 1.0: P_{mine, SHIELD} = 99.0 * (1.0 - progress)
   If progress >= 1.0: P_{mine, SHIELD} = max(0.0001, 1.0 / (1.0 + (S_alt - 2,100,000) / 1,000,000))

### 5.2 The 1–99 Polynomial Acceptance Window
During a mining cycle, the node normalizes its current 1–99 mining power into the unit interval and raises it to the exponent 2.75 to compute the acceptance threshold T_accept in (0, 99.0]:

R_norm = max(10^-7, min(1.0, P_mine / 99.0))
T_accept = 99.0 * (R_norm)^2.75

For each attempt a in {1, 2, ..., A_max}, the miner constructs a candidate seed inside the **Infinite Variable** space by binding the block identifier Seed_block, the node's active variable slot Slot_node, the node's daily 1–99 assignment V_assigned, and the attempt counter a:

H_cand = SHA256(Seed_block || Slot_node || V_assigned || a)

The candidate hash is then projected onto the continuous 1–99 variable continuum [0.0, 99.0) with 10^-6 precision:

V_point = (int(MD5(H_cand)) mod 99,000,000) / 1,000,000.0

A valid block proof is found as soon as V_point <= T_accept. When P_mine is near 99.0, T_accept is near 99.0, allowing rapid block discovery. As P_mine approaches 1.0 or below, the exponent 2.75 narrows the acceptance window exponentially within the Infinite Variable domain, enforcing strict cryptographic scarcity.

---

## 6. Cryptographic IP Obfuscation and Variable Slot Routing

A major privacy and security flaw in standard peer-to-peer blockchains (such as Bitcoin and Ethereum) is that peer nodes broadcast and store raw plaintext IPv4/IPv6 addresses (`ip:port`) inside peer tables (`peers.dat` or `known_peers.json`). This exposes node operators to targeted DDoS attacks, traffic analysis, ISP throttling, and physical geolocation.

VariableCoin eliminates plaintext IP storage and transmission through the **Cryptographic IP Security Layer** (`IPSecurityLayer`), which leverages the **Infinite Variable** coordinate system and 24-hour epoch rotation to shield network endpoints.

### 6.1 Variable-Slot Key Derivation and Stream Cipher Encryption
Whenever a node discovers or announces an endpoint (including its own external IP mapped via UPnP), the plaintext `ip:port` string is immediately encrypted before touching disk or P2P payloads. The encryption key K_slot is derived from the protocol's 256-bit secret salt, the target variable coordinate Slot_var, and the active 24-hour epoch E:

K_slot = SHA256("VARIABLE_PROTOCOL_256BIT_IP_SHIELD_V1" || Slot_var || E)

To encrypt a plaintext endpoint P:
1. A cryptographic 96-bit random nonce N (12 bytes) is generated via `secrets.token_bytes(12)`.
2. A 256-bit counter-mode SHA-256 keystream is generated for each 32-byte block i:
   S_i = SHA256(K_slot || N || uint32_be(i))
3. The ciphertext C is produced via bitwise XOR (C = P XOR S), and a 128-bit truncated HMAC-SHA256 integrity tag M is computed over the nonce and ciphertext:
   M = HMAC-SHA256(K_slot, N || C)[0:16]
4. The resulting token is Base64-URL encoded and prefixed as an opaque variable token:
   Token_IP = "ENC_IP_" || Base64URL(N || M || C)

### 6.2 Ephemeral In-Memory Decryption and Blind Fingerprinting
When a peer initiates an outbound socket connection, `decrypt_endpoint` validates the HMAC tag in constant time (`hmac.compare_digest`) across candidate slots (Slot_var, "GLOBAL_SLOT") and candidate epochs (E, E-1) to ensure zero-downtime connectivity across 24-hour UTC boundaries. The plaintext IP exists strictly in volatile CPU registers during socket dial-out and is never written to disk.

To allow nodes to deduplicate peer tables and display connected peers in the user interface without decrypting their IPs, the protocol computes an irreversible blind fingerprint:

ID_blind = "BLIND_" || SHA256(Salt || "BLIND:" || Endpoint)[0:16]

---

## 7. Full-Archive 1–99 Active/Passive Storage and Hardware Governance

As a blockchain grows, full nodes normally face an unavoidable trade-off: either keep the entire ledger state active in memory/database indexes (causing severe RAM exhaustion and disk I/O bottlenecks on consumer hardware) or prune historical blocks (sacrificing sovereign full-archive auditability).

VariableCoin solves this through the **Variable Storage Engine** (`VariableStorageEngine`) and the **Variable Rule Hardware Governor** (`VariableRuleGovernor`), applying the **1–99 Variable Rule** to physical storage and memory management.

### 7.1 99-Block Cluster Partitioning
Instead of pooling thousands of blocks into a single monolithic directory or flat file, physical blocks on disk are partitioned into discrete clusters of exactly 99 blocks (`cluster_1`, `cluster_2`, ..., `cluster_N`). For any block at index h >= 1:

Cluster_ID(h) = floor((h - 1) / 99) + 1
Offset_cluster(h) = ((h - 1) mod 99) + 1

Every block written to disk preserves 100% of its transaction history permanently alongside a cryptographic SHA-256 payload commitment (`data_snapshot_hash`):

H_snapshot = SHA256(CanonicalJSON(Transactions))

### 7.2 Dynamic 1–99 Active/Passive RAM Projection
While 100% of blocks remain safely archived on disk, the proportion of blocks held **ACTIVE** in volatile RAM at any given moment is governed by the node's effective 1–99 value V_eff in [1, 99].

For each block (C, h), the protocol computes a deterministic 1–99 activation requirement V_req in {1, 2, ..., 99} for the current epoch E and variable slot Slot_node:

V_req(C, h, E) = (int(SHA256("BLOCK_REQUIREMENT_" || C || h || E || Slot_node)) mod 99) + 1

The storage engine then projects the block into memory according to the 1–99 comparison rule:
* **ACTIVE State (V_eff >= V_req):** The block's full transaction list is loaded into RAM for zero-latency inspection and validation.
* **PASSIVE State (V_eff < V_req):** The transaction payload is stripped from RAM (`transactions = []`), leaving only a lightweight header projection in memory while the full block remains dormant on disk. Whenever a user or peer queries a balance, token inventory, or historical transaction (`full_data=True`), the engine transparently hydrates the exact required block from disk on demand.

### 7.3 Thermal and Disk Safety Governor
To protect consumer laptops and desktop machines from hardware degradation, `VariableRuleGovernor` continuously monitors free disk space (D_free in MB) and CPU processing latency (dt_proc vs. `THERMAL_TIME_THRESHOLD` = 0.85 s). The node's effective 1–99 value V_eff is automatically throttled downward—and never exceeds V_assigned—when hardware pressure is detected:

* If D_free < 250 MB: V_eff = 1
* If dt_proc > 0.85 s (Thermal Pressure): V_eff = max(1, floor(V_assigned / 3))
* If 250 MB <= D_free < 500 MB: V_eff = max(1, floor(V_assigned / 2))
* Otherwise: V_eff = V_assigned

Every 24 hours, the background daemon triggers `rotate_all_blocks_for_new_epoch`, reassigning the node's variable slot and 1–99 capacity value and rebalancing active/passive memory projections across the entire network without losing a single byte of historical ledger data.

---

## 8. Sovereign Node Identity, SECP256k1 Cryptography, and UPnP Mesh

VariableCoin is designed to operate as a sovereign desktop node without relying on centralized cloud infrastructure:

1. **SECP256k1 256-Bit Signatures:** All wallets are generated from 256-bit cryptographically secure random scalars (`secrets.token_bytes(32)`) on the `SECP256k1` elliptic curve (0 < k < n). Every protocol mutation (`/protocol/act`) and peer transfer (`/transfer`) cryptographically verifies that the derived verifying key matches the sender's public address before mutating state.
2. **Persistent Hardware-Salted Node Identity:** Upon initial launch, `NodeIdentityAndUPnPManager` combines the host's hardware MAC identifier (`uuid.getnode()`) with a 64-bit random cryptographic salt to generate a permanent `NODE_...` identifier stored in `node_identity.json`. This guarantees that a node retains its 24-hour Infinite Variable slot and 1–99 ratio across router reboots or dynamic IP changes.
3. **Zero-Configuration UPnP Port Forwarding:** Using `miniupnpc`, the node automatically discovers local Internet Gateway Devices (IGD), maps TCP port 6000 and UDP port 6001, and immediately passes the discovered external IP through `IPSecurityLayer.encrypt_endpoint` and `fingerprint_endpoint`. If a firewall blocks inbound connections, the node seamlessly falls back to outbound synchronization.

---

## 9. Conclusion

We have presented VariableCoin, a complete Layer-1 blockchain protocol governed by the **1–99 Variable Rule** and the **Infinite Variable** architecture. By replacing external order-book dependence with tiered Shield Coin burning, substituting static hash-prefix brute-forcing with 1–99 Infinite Variable mining, shielding peer IP addresses with epoch-rotated stream ciphers, and dynamically projecting ledger state between active RAM and passive disk clusters according to real-time hardware telemetry, VariableCoin delivers a self-stabilizing, privacy-preserving, and hardware-sustainable sovereign monetary network.
