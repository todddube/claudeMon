class Claudemon < Formula
  include Language::Python::Virtualenv

  desc "Task manager for Claude Code"
  homepage "https://github.com/todddube/claudeMon"
  license "MIT"
  head "https://github.com/todddube/claudeMon.git", branch: "main"

  depends_on "python@3.14"

  # The build backend (pyproject needs setuptools>=77); Homebrew builds without network isolation.
  resource "setuptools" do
    url "https://files.pythonhosted.org/packages/70/b3/c19426f783614d625699a4b247faf628ea9ab1db228674491767b417f9e1/setuptools-84.2.1.tar.gz"
    sha256 "3ff8b3b5492a0aa66960f4419365a86b84e013070d4313e4d4a6894f5d64d6bc"
  end

  def install
    virtualenv_install_with_resources
  end

  def caveats
    <<~EOS
      Run `claudemon install` after installing: Homebrew may not write to ~/.claude,
      so claudeMon sets up its tap itself.

      Run `claudemon uninstall` before `brew uninstall claudemon`, so the tap is
      removed from your Claude Code settings.

      To upgrade: brew upgrade --fetch-HEAD claudemon
    EOS
  end

  test do
    ENV["CLAUDE_CONFIG_DIR"] = testpath/"claude"
    assert_match "claudemon", shell_output("#{bin}/claudemon --version")
  end
end
