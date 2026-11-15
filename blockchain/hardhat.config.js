require("@nomicfoundation/hardhat-toolbox");
require("dotenv").config({ path: "../.env" });

module.exports = {
  solidity: {
    version: "0.8.28",
    settings: {
      optimizer: { enabled: true, runs: 200 },
    },
  },
  networks: {
    localhost: {
      url: process.env.BLOCKCHAIN_RPC_URL || "http://127.0.0.1:8545",
      chainId: Number(process.env.BLOCKCHAIN_CHAIN_ID || "31337"),
    },
    configured: {
      url: process.env.BLOCKCHAIN_RPC_URL || "http://127.0.0.1:8545",
      chainId: Number(process.env.BLOCKCHAIN_CHAIN_ID || "31337"),
      ...(process.env.BLOCKCHAIN_PRIVATE_KEY
        ? { accounts: [process.env.BLOCKCHAIN_PRIVATE_KEY] }
        : {}),
    },
  },
};
