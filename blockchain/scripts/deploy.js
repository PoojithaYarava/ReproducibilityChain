const { ethers } = require("hardhat");

async function main() {
  const [deployer] = await ethers.getSigners();
  const registry = await ethers.deployContract("ExperimentRegistry");
  await registry.waitForDeployment();

  console.log("Network chain ID:", (await ethers.provider.getNetwork()).chainId.toString());
  console.log("Deployer:", deployer.address);
  console.log("ExperimentRegistry:", await registry.getAddress());
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
