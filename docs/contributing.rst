.. _contributing:

Contributing
************

We accept code contributions to amaGama, please use GitHub pull requests for
your changes.


Preparations
------------

You will need a local working copy of amaGama. The best way to achieve that is
to follow the :ref:`installation guidelines <installation>`.


Coding style
------------

Please follow the :ref:`Translate Toolkit Style Guide <toolkit:styleguide>`.

Code is linted with `ruff <https://docs.astral.sh/ruff/>`_. Install the git
pre-commit hook once per checkout (via `prek <https://github.com/j178/prek>`_,
a faster drop-in for `pre-commit <https://pre-commit.com>`_, both installed by
``requirements/dev.txt``) so it runs automatically:

.. code-block:: bash

    $ prek install

You can also run it manually against the whole tree at any time:

.. code-block:: bash

    $ prek run --all-files


TODO
----

An incomplete list of possible TODO items:

- Improve web interface
- Custom index config for source languages not supported by default PostgreSQL
  install
- Keep track of file's mtime to avoid expensive reparses
- Use memcached to cache results
- Use more permanent caching of Levenshtein distances?
- Use PostgreSQL built-in Levenshtein functions?
- Full text search
- Other search methods and options
- Further documenting of API
- Document the commands
- Document how to deploy amaGama using Apache or other web server
