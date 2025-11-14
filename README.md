# LeagueUnlocked

```powershell
# LeagueUnlocked Development Setup
# Copy and paste this entire block into PowerShell to set up dev environment instantly

# Create conda environment with Python 3.11
conda create -n leagueunlocked python=3.11 -y

# Activate the environment
conda activate leagueunlocked

# Clone the repository
git clone https://github.com/Alban1911/LU-source.git

# Navigate to project directory (adjust path as needed)
cd ".\LU-source"

# Switch to dev branch (submodules only exist on dev, not on main)
git checkout dev

# Initialize and update submodules (required!)
git submodule update --init --recursive

# Install all dependencies
pip install -r requirements.txt

# Ready to develop! Run main.py as administrator when testing
echo "Development environment ready! Use 'conda activate leagueunlocked' to activate this environment in future sessions."
```
