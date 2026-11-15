const { expect } = require("chai");
const { ethers } = require("hardhat");

describe("ExperimentRegistry", function () {
  async function deploy() {
    const [researcher, other] = await ethers.getSigners();
    const registry = await ethers.deployContract("ExperimentRegistry");
    await registry.waitForDeployment();
    return { registry, researcher, other };
  }

  it("registers an evidence commitment and reads it back", async function () {
    const { registry, researcher } = await deploy();
    const manifestHash = ethers.keccak256(ethers.toUtf8Bytes("manifest fixture"));
    const tx = await registry.registerExperiment("experiment-1", 1, manifestHash);
    const receipt = await tx.wait();
    const record = await registry.getExperiment("experiment-1", 1);

    expect(receipt.status).to.equal(1);
    expect(record.manifestHash).to.equal(manifestHash);
    expect(record.researcher).to.equal(researcher.address);
    expect(record.exists).to.equal(true);
    expect(
      await registry.verifyExperiment("experiment-1", 1, manifestHash),
    ).to.equal(true);
  });

  it("rejects a duplicate ID and version but permits a new version", async function () {
    const { registry } = await deploy();
    const firstHash = ethers.keccak256(ethers.toUtf8Bytes("v1"));
    const secondHash = ethers.keccak256(ethers.toUtf8Bytes("v2"));

    await registry.registerExperiment("same-experiment", 1, firstHash);
    await expect(
      registry.registerExperiment("same-experiment", 1, secondHash),
    ).to.be.revertedWithCustomError(registry, "DuplicateRegistration");
    await expect(
      registry.registerExperiment("same-experiment", 2, secondHash),
    ).not.to.be.reverted;
  });

  it("rejects empty identifiers and empty evidence hashes", async function () {
    const { registry } = await deploy();
    const nonzeroHash = ethers.keccak256(ethers.toUtf8Bytes("manifest"));

    await expect(
      registry.registerExperiment("", 1, nonzeroHash),
    ).to.be.revertedWithCustomError(registry, "EmptyExperimentId");
    await expect(
      registry.registerExperiment("experiment", 1, ethers.ZeroHash),
    ).to.be.revertedWithCustomError(registry, "EmptyManifestHash");
  });

  it("returns false for a missing record or changed commitment", async function () {
    const { registry } = await deploy();
    const hash = ethers.keccak256(ethers.toUtf8Bytes("original"));
    const changed = ethers.keccak256(ethers.toUtf8Bytes("changed"));
    await registry.registerExperiment("experiment", 1, hash);

    expect(await registry.verifyExperiment("experiment", 1, changed)).to.equal(false);
    expect(await registry.verifyExperiment("missing", 1, hash)).to.equal(false);
  });
});
