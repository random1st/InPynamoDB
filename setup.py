from setuptools import setup, find_packages

install_requires = [
    'PynamoDB==3.3.0',
    'aiobotocore==0.10.2'
]

python_requires = '>=3.5'


def version():
    with open("VERSION") as f:
        return f.read().strip()


setup(
    name='InPynamoDB',
    version=__import__('inpynamodb').__version__,
    packages=find_packages(),
    author='Sunghyun Lee',
    author_email='jolacaleb@gmail.com',
    description='Asynchronous implementation of PynamoDB',
    zip_safe=False,
    license='MIT',
    keywords='python dynamodb amazon async pynamodb',
    install_requires=install_requires,
    classifiers=[
        'Development Status :: 1 - Developing',
        'Intended Audience :: Developers',
        'Programming Language :: Python',
        'Operating System :: OS Independent',
        'Programming Language :: Python :: 3.6',
        'License :: OSI Approved :: MIT License',
    ]
)
