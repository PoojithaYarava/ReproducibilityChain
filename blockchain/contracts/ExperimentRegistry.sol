// SPDX-License-Identifier: MIT
pragma solidity ^0.8.28;

contract ExperimentRegistry {
    struct ExperimentRecord {
        bytes32 manifestHash;
        address researcher;
        uint64 timestamp;
        bool exists;
    }

    mapping(bytes32 => ExperimentRecord) private records;

    event ExperimentRegistered(
        string experimentId,
        uint256 indexed version,
        bytes32 indexed manifestHash,
        address indexed researcher,
        uint64 timestamp
    );

    error EmptyExperimentId();
    error EmptyManifestHash();
    error DuplicateRegistration(string experimentId, uint256 version);

    function registerExperiment(
        string calldata experimentId,
        uint256 version,
        bytes32 manifestHash
    ) external {
        if (bytes(experimentId).length == 0) revert EmptyExperimentId();
        if (manifestHash == bytes32(0)) revert EmptyManifestHash();

        bytes32 key = _key(experimentId, version);
        if (records[key].exists) revert DuplicateRegistration(experimentId, version);

        uint64 registeredAt = uint64(block.timestamp);
        records[key] = ExperimentRecord({
            manifestHash: manifestHash,
            researcher: msg.sender,
            timestamp: registeredAt,
            exists: true
        });
        emit ExperimentRegistered(
            experimentId,
            version,
            manifestHash,
            msg.sender,
            registeredAt
        );
    }

    function verifyExperiment(
        string calldata experimentId,
        uint256 version,
        bytes32 expectedManifestHash
    ) external view returns (bool) {
        ExperimentRecord storage record = records[_key(experimentId, version)];
        return record.exists && record.manifestHash == expectedManifestHash;
    }

    function getExperiment(
        string calldata experimentId,
        uint256 version
    ) external view returns (ExperimentRecord memory) {
        return records[_key(experimentId, version)];
    }

    function _key(
        string calldata experimentId,
        uint256 version
    ) private pure returns (bytes32) {
        return keccak256(abi.encode(experimentId, version));
    }
}
