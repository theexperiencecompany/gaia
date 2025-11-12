# Contributing to GAIA

Thank you for your interest in contributing to GAIA! 🎉

## 📚 Documentation

For comprehensive contribution guidelines, please visit our documentation:

### Getting Started

- **[Development Setup](https://docs.heygaia.io/developers/development-setup)** - Set up your local environment
- **[Contributing Guidelines](https://docs.heygaia.io/developers/contributing)** - Overview of contribution process
- **[Code of Conduct](https://github.com/heygaia/gaia/blob/master/CODE_OF_CONDUCT.md)** - Community standards

### Developer Guides

- **[Code Style Guide](https://docs.heygaia.io/developers/code-style)** - Coding standards and best practices
- **[Commands Reference](https://docs.heygaia.io/developers/commands)** - All available mise commands
- **[Pull Request Guide](https://docs.heygaia.io/developers/pull-requests)** - How to submit changes

### Configuration

- **[Environment Variables](https://docs.heygaia.io/configuration/environment-variables)** - Configuration reference
- **[Conventional Commits](https://docs.heygaia.io/configuration/conventional-commits)** - Commit message format
- **[Docker Setup](https://docs.heygaia.io/configuration/docker)** - Container configuration

## Quick Start

```bash
# 1. Fork and clone the repository
git clone https://github.com/YOUR_USERNAME/gaia.git
cd gaia

# 2. Install mise (if not already installed)
curl https://mise.run | sh

# 3. Copy environment files
cp backend/.env.example backend/.env
cp frontend/.env.example frontend/.env
# Configure your API keys in the .env files

# 4. Run automated setup
mise setup

# 5. Create a feature branch
git checkout -b feature/your-feature-name

# 6. Make changes and test
mise lint:all      # Check code quality
mise test          # Run tests (from backend/)

# 7. Commit and push
git commit -m "feat: your changes"
git push origin feature/your-feature-name

# 8. Create a pull request on GitHub
```

## Need Help?

- **[Discord](https://discord.heygaia.io)** - Join our community
- **[GitHub Issues](https://github.com/heygaia/gaia/issues)** - Report bugs or request features
- **[Discussions](https://github.com/heygaia/gaia/discussions)** - Ask questions

## Additional Resources

- [FastAPI Documentation](https://fastapi.tiangolo.com/)
- [Next.js Documentation](https://nextjs.org/docs)
- [Complete Documentation](https://docs.heygaia.io)
