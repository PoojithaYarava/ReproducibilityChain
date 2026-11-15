import os
import logging

from web3 import Web3

logger = logging.getLogger("reproducibility_chain.blockchain")

ABI = [
    {
        "inputs": [
            {"internalType": "string", "name": "experimentId", "type": "string"},
            {"internalType": "uint256", "name": "version", "type": "uint256"},
            {"internalType": "bytes32", "name": "manifestHash", "type": "bytes32"},
        ],
        "name": "registerExperiment",
        "outputs": [],
        "stateMutability": "nonpayable",
        "type": "function",
    },
    {
        "inputs": [
            {"internalType": "string", "name": "experimentId", "type": "string"},
            {"internalType": "uint256", "name": "version", "type": "uint256"},
            {"internalType": "bytes32", "name": "expectedManifestHash", "type": "bytes32"},
        ],
        "name": "verifyExperiment",
        "outputs": [{"internalType": "bool", "name": "", "type": "bool"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [
            {"internalType": "string", "name": "experimentId", "type": "string"},
            {"internalType": "uint256", "name": "version", "type": "uint256"},
        ],
        "name": "getExperiment",
        "outputs": [
            {
                "components": [
                    {"internalType": "bytes32", "name": "manifestHash", "type": "bytes32"},
                    {"internalType": "address", "name": "researcher", "type": "address"},
                    {"internalType": "uint64", "name": "timestamp", "type": "uint64"},
                    {"internalType": "bool", "name": "exists", "type": "bool"},
                ],
                "internalType": "struct ExperimentRegistry.ExperimentRecord",
                "name": "",
                "type": "tuple",
            }
        ],
        "stateMutability": "view",
        "type": "function",
    },
]


class BlockchainError(RuntimeError):
    def __init__(
        self,
        message: str,
        tx_hash: str | None = None,
        block_number: int | None = None,
        tx_status: str = "failed",
        signer_address: str | None = None,
        chain_id: int | None = None,
    ):
        super().__init__(message)
        self.tx_hash = tx_hash
        self.block_number = block_number
        self.tx_status = tx_status
        self.signer_address = signer_address
        self.chain_id = chain_id


def _client():
    rpc_url = os.getenv("BLOCKCHAIN_RPC_URL", "")
    private_key = os.getenv("BLOCKCHAIN_PRIVATE_KEY", "")
    contract_address = os.getenv("BLOCKCHAIN_CONTRACT_ADDRESS", "")
    if not rpc_url or not private_key or not contract_address:
        raise BlockchainError(
            "Blockchain is not configured. Start the local Hardhat node, deploy "
            "ExperimentRegistry, and set its RPC URL, test-wallet private key, "
            "and deployed contract address in the backend environment."
        )
    web3 = Web3(Web3.HTTPProvider(rpc_url, request_kwargs={"timeout": 10}))
    if not web3.is_connected():
        raise BlockchainError("Unable to connect to the configured blockchain RPC endpoint")
    try:
        account = web3.eth.account.from_key(private_key)
        contract = web3.eth.contract(
            address=Web3.to_checksum_address(contract_address), abi=ABI
        )
    except (ValueError, TypeError) as exc:
        raise BlockchainError("Invalid blockchain signer or contract address") from exc
    expected_chain_id = int(os.getenv("BLOCKCHAIN_CHAIN_ID", "31337"))
    if web3.eth.chain_id != expected_chain_id:
        raise BlockchainError(
            f"Connected chain ID {web3.eth.chain_id} does not match configured "
            f"chain ID {expected_chain_id}"
        )
    return web3, account, contract


def anchor_manifest(experiment_id: str, version: int, manifest_hash: str) -> dict:
    web3, account, contract = _client()
    tx_hash_hex: str | None = None
    try:
        digest = bytes.fromhex(manifest_hash.removeprefix("sha256:"))
        if len(digest) != 32:
            raise ValueError("manifest hash must be SHA-256")
        function = contract.functions.registerExperiment(
            experiment_id, version, digest
        )
        nonce = web3.eth.get_transaction_count(account.address, "pending")
        transaction = function.build_transaction(
            {
                "from": account.address,
                "nonce": nonce,
                "chainId": web3.eth.chain_id,
                "gas": function.estimate_gas({"from": account.address}) + 20_000,
                "gasPrice": web3.eth.gas_price,
            }
        )
        signed = account.sign_transaction(transaction)
        tx_hash = web3.eth.send_raw_transaction(signed.raw_transaction)
        tx_hash_hex = tx_hash.hex()
        receipt = web3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)
        if receipt.status != 1:
            raise BlockchainError(
                "Blockchain transaction was mined but reverted",
                tx_hash_hex,
                receipt.blockNumber,
                "failed",
                account.address,
                web3.eth.chain_id,
            )
        record = contract.functions.getExperiment(experiment_id, version).call()
        stored_hash = bytes(record[0])
        if (
            not record[3]
            or stored_hash != digest
            or Web3.to_checksum_address(record[1]) != account.address
        ):
            raise BlockchainError(
                "Transaction was mined, but contract read-back did not match",
                tx_hash_hex,
                receipt.blockNumber,
                "unverified",
                account.address,
                web3.eth.chain_id,
            )
        return {
            "transaction_hash": tx_hash_hex,
            "status": "confirmed",
            "block_number": receipt.blockNumber,
            "signer_address": account.address,
            "chain_id": web3.eth.chain_id,
        }
    except BlockchainError:
        raise
    except Exception as exc:
        if tx_hash_hex:
            logger.exception("Broadcast blockchain transaction was not confirmed")
            raise BlockchainError(
                f"Transaction {tx_hash_hex} was submitted, but confirmation could not be established; check transaction status on the configured chain",
                tx_hash_hex,
                tx_status="pending",
                signer_address=account.address,
                chain_id=web3.eth.chain_id,
            ) from exc
        logger.exception("Blockchain transaction could not be submitted")
        raise BlockchainError(
            "Blockchain registration failed before transaction submission; review backend logs"
        ) from exc


def verify_manifest(experiment_id: str, version: int, manifest_hash: str) -> dict:
    web3, _, contract = _client()
    digest = bytes.fromhex(manifest_hash.removeprefix("sha256:"))
    try:
        record = contract.functions.getExperiment(experiment_id, version).call()
        verified_by_contract = contract.functions.verifyExperiment(
            experiment_id, version, digest
        ).call()
    except Exception as exc:
        logger.exception("Blockchain read-back failed")
        raise BlockchainError("Blockchain read-back failed; review backend logs") from exc
    return {
        "chain_id": web3.eth.chain_id,
        "exists": bool(record[3]),
        "manifest_matches": (
            bool(record[3])
            and bytes(record[0]) == digest
            and bool(verified_by_contract)
        ),
        "researcher": record[1],
        "timestamp": int(record[2]),
    }


def network_status() -> dict:
    rpc_url = os.getenv("BLOCKCHAIN_RPC_URL", "")
    contract_address = os.getenv("BLOCKCHAIN_CONTRACT_ADDRESS", "")
    private_key = os.getenv("BLOCKCHAIN_PRIVATE_KEY", "")
    expected_chain_id = int(os.getenv("BLOCKCHAIN_CHAIN_ID", "31337"))
    result = {
        "rpc_configured": bool(rpc_url),
        "contract_configured": bool(contract_address),
        "signer_configured": bool(private_key),
        "connected": False,
        "contract_deployed": False,
        "expected_chain_id": expected_chain_id,
        "chain_id": None,
    }
    if not rpc_url:
        return result
    try:
        web3 = Web3(Web3.HTTPProvider(rpc_url, request_kwargs={"timeout": 5}))
        if not web3.is_connected():
            return result
        result["connected"] = True
        result["chain_id"] = web3.eth.chain_id
        if contract_address:
            result["contract_deployed"] = bool(
                web3.eth.get_code(Web3.to_checksum_address(contract_address))
            )
    except (ValueError, TypeError):
        return result
    return result
