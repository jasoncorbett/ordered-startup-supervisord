##TWINE_REPOSITORY:  The pypi repository. Should be a section in the config file ~/.pypirc. (default: pypi)
export TWINE_REPOSITORY?=pypi

default: help

build: ## Build package
	python setup.py build

sdist: ## Create source dist file
	python setup.py sdist

wheel: ## Create wheel
	python setup.py bdist_wheel --universal

upload-sdist: sdist ## Upload sdist
	twine upload --verbose dist/*.tar.gz

upload-wheel: wheel ## Upload wheel
	twine upload --verbose  dist/*.whl

upload-all: ## Upload all
upload-all: upload-sdist upload-wheel

clean: ## Clean
	$(RM) -r build/
	$(RM) -r dist/
	$(RM) -r supervisord_dependent_startup.egg-info
	$(RM) -r .tox/
	-find . -name "*.pyc"      -delete 2>/dev/null; true
	-find . -name __pycache__  -delete 2>/dev/null; true

help: ## Show this help
	@echo "==================================="
	@echo "    Available targets"
	@echo "==================================="
	@fgrep -h "##" $(MAKEFILE_LIST) | fgrep -v fgrep | sed -rn "s/(\S+)\s*:.+?\s##\s?\s(.+)/\1 \"\2\"/p" | xargs printf " %-20s : %5s\n"
	@echo
	@echo "-----------------------------------------------------------------"
	@echo "  Available environment configurations to set with 'make [VARIABLE=value] <target>'"
	@echo "-----------------------------------------------------------------"
	@fgrep -h "##" $(MAKEFILE_LIST) | fgrep -v fgrep | sed -rn "s/^##\s*(\S+)\s*:\s*(.+)/\1 \"\2\"/p" | xargs printf " %-20s    : %5s\n"
	@echo
	@echo -e "Example:\n make TWINE_REPOSITORY=pypitest"
	@echo