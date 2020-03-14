Python wrapper for Vk.com (Vkontakte.ru) API. 
This fork supports multi-object responses and silent iteration over errors.

[![PyPI](https://img.shields.io/pypi/pyversions/vk.svg)](https://pypi.org/project/vk/ "Latest version on PyPI")
[![Travis](https://travis-ci.com/voronind/vk.svg?branch=master)](https://travis-ci.com/voronind/vk "Travis CI")
[![Docs](https://readthedocs.org/projects/vk/badge/?version=stable)](https://vk.readthedocs.io/en/latest/ "Read the docs")
[![codecov](https://codecov.io/gh/voronind/vk/branch/master/graph/badge.svg)](https://codecov.io/gh/voronind/vk "Coverage")

# Quickstart

## Install

This version:
```sh
$ pip install git+https://github.com/ashvardanian/PyScrapeVk.git
```

Original version:
```sh
$ pip install vk
```

## Usage

```python
>>> import ig
>>> api = vk.API(access_token = '', lang = 'en', v = '5.103')
>>> api.session.proxies = self.proxies_dict()
>>> list(api.users.get(user_ids=1))

[{'first_name': 'Pavel', 'last_name': 'Durov', 'id': 1}]
```

See [Vk docs](https://vk.com/dev/methods) for detailed API guide.

# More info

Read full [documentation](https://vk.readthedocs.org)
