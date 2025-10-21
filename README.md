# League Unlocked

```powershell
# LeagueUnlocked Development Setup
# Copy and paste this entire block into PowerShell to set up dev environment instantly

# Create conda environment with Python 3.11
conda create -n leagueunlocked python=3.11 -y

# Activate the environment
conda activate leagueunlocked

# Clone the repository
git clone https://github.com/AlbanCliquet/LeagueUnlocked.git

# Navigate to project directory (adjust path as needed)
cd ".\LeagueUnlocked"

# Switch to dev branch
git checkout dev

# Install all dependencies
pip install -r requirements.txt

# Ready to develop! Run main.py as administrator when testing
echo "Development environment ready! Use 'conda activate leagueunlocked' to activate this environment in future sessions."
```
